"""Background run manager with a Server-Sent Events fan-out.

Only one run executes at a time. That is a deliberate choice: the product claim
is about bounded memory on one edge device, and running several mosaics in
parallel would make the resource numbers meaningless.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

from .. import config
from ..pipeline import run_pipeline
from ..storage import RunStore, utcnow


@dataclass
class Job:
    run_id: str
    name: str
    source: str | list[str]
    settings: config.PipelineSettings
    status: str = "queued"
    created_at: str = field(default_factory=utcnow)
    finished_at: str | None = None
    error: str | None = None
    report: dict[str, Any] | None = None
    events: list[dict] = field(default_factory=list)
    subscribers: list[queue.Queue] = field(default_factory=list)
    thread: threading.Thread | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)

    # -- event plumbing ---------------------------------------------------
    def emit(self, event: dict) -> None:
        with self.lock:
            self.events.append(event)
            # keep the replay buffer bounded on very long runs
            if len(self.events) > 4000:
                self.events = self.events[-2000:]
            if event.get("type") == "finished":
                self.status = event.get("status", "succeeded")
                self.finished_at = utcnow()
            elif event.get("type") == "started":
                self.status = "running"
            dead = []
            for q in self.subscribers:
                try:
                    q.put_nowait(event)
                except queue.Full:  # pragma: no cover
                    dead.append(q)
            for q in dead:
                self.subscribers.remove(q)

    def subscribe(self) -> tuple[queue.Queue, list[dict]]:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self.lock:
            history = list(self.events)
            self.subscribers.append(q)
        return q, history

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def to_dict(self, full: bool = False) -> dict:
        d = {
            "run_id": self.run_id,
            "name": self.name,
            "status": self.status,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "settings": self.settings.to_dict(),
            "source": self.source if isinstance(self.source, str) else list(self.source),
            "event_count": len(self.events),
        }
        if full and self.report:
            d["report"] = self.report
        return d


class JobManager:
    def __init__(self, store: RunStore):
        self.store = store
        self._jobs: dict[str, Job] = {}
        self._active: str | None = None
        self._lock = threading.RLock()

    def active_run_id(self) -> str | None:
        with self._lock:
            if self._active:
                job = self._jobs.get(self._active)
                if job and job.status in ("queued", "running"):
                    return self._active
                self._active = None
            return None

    def get(self, run_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(run_id)

    def start(self, name: str, source: str | list[str], settings: config.PipelineSettings) -> Job:
        with self._lock:
            if self.active_run_id():
                raise RuntimeError(
                    f"a run is already in progress ({self._active}); EdgeOrtho executes one "
                    "mosaic at a time so the resource measurements stay meaningful"
                )
            import uuid
            from datetime import datetime

            run_id = (
                datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
            )
            job = Job(run_id=run_id, name=name, source=source, settings=settings)
            self._jobs[run_id] = job
            self._active = run_id

            self.store.upsert_run(
                {
                    "run_id": run_id,
                    "name": name,
                    "source": source if isinstance(source, str) else f"{len(source)} uploaded file(s)",
                    "created_at": job.created_at,
                    "status": "running",
                    "profile": settings.profile,
                    "preset": settings.preset,
                    "settings": settings.to_dict(),
                }
            )
            job.thread = threading.Thread(target=self._run, args=(job,), daemon=True)
            job.thread.start()
            return job

    def _run(self, job: Job) -> None:
        try:
            report = run_pipeline(
                job.source,
                settings=job.settings,
                run_id=job.run_id,
                name=job.name,
                emit=job.emit,
            )
            job.report = report
            self._persist(job, report)
        except Exception as exc:  # pragma: no cover - defensive
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            job.emit({"type": "finished", "run_id": job.run_id, "status": "failed"})
            self.store.upsert_run(
                {
                    "run_id": job.run_id,
                    "name": job.name,
                    "status": "failed",
                    "error": job.error,
                    "finished_at": utcnow(),
                }
            )
        finally:
            with self._lock:
                if self._active == job.run_id:
                    self._active = None

    def _persist(self, job: Job, report: dict) -> None:
        output = report.get("output") or {}
        metrics = report.get("metrics") or {}
        summary = report.get("metadata_summary") or {}
        self.store.upsert_run(
            {
                "run_id": job.run_id,
                "name": job.name,
                "source": (
                    job.source if isinstance(job.source, str) else f"{len(job.source)} uploaded file(s)"
                ),
                "created_at": report.get("created_at") or job.created_at,
                "finished_at": report.get("finished_at"),
                "status": report.get("status", "succeeded"),
                "profile": job.settings.profile,
                "preset": job.settings.preset,
                "frames_total": metrics.get("frames_total"),
                "frames_ok": metrics.get("frames_accepted"),
                "output_bytes": metrics.get("output_bytes"),
                "wall_clock_s": metrics.get("wall_clock_s"),
                "peak_rss_mb": metrics.get("peak_rss_mb"),
                "settings": job.settings.to_dict(),
                "summary": {**summary, "source_kind": _source_kind(job.source), "error": report.get("error")},
                "stages": report.get("stages"),
                "metrics": metrics,
                "output": output,
                "report": report,
                "artifacts": report.get("artifacts"),
                "error": report.get("error"),
            }
        )


def _source_kind(source) -> str:
    if isinstance(source, list):
        return "upload"
    text = str(source).replace("\\", "/").lower()
    if "/data/raw/" in text or text.endswith("raw"):
        return "sample"
    return "local_folder"
