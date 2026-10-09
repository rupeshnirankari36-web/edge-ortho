"""Local persistence for runs, stages and aggregate performance evidence.

SQLite is used because the whole product premise is local-first: no server, no
account, no upload. The store keeps the complete run report as JSON so history
and the Performance Lab read exactly what the pipeline produced, and it never
recomputes or invents a value at read time.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import DB_PATH, ensure_dirs

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    source        TEXT,
    created_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL,
    profile       TEXT,
    preset        TEXT,
    frames_total  INTEGER,
    frames_ok     INTEGER,
    output_bytes  INTEGER,
    wall_clock_s  REAL,
    peak_rss_mb   REAL,
    settings_json TEXT,
    summary_json  TEXT,
    stages_json   TEXT,
    metrics_json  TEXT,
    output_json   TEXT,
    report_json   TEXT,
    artifacts_json TEXT,
    error         TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_profile ON runs(profile);
"""


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RunStore:
    def __init__(self, path: Path | str | None = None):
        ensure_dirs()
        self.path = Path(path or DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    # -- writes -----------------------------------------------------------
    def upsert_run(self, record: dict[str, Any]) -> None:
        row = {
            "run_id": record["run_id"],
            "name": record.get("name") or record["run_id"],
            "source": record.get("source"),
            "created_at": record.get("created_at") or utcnow(),
            "finished_at": record.get("finished_at"),
            "status": record.get("status") or "pending",
            "profile": record.get("profile"),
            "preset": record.get("preset"),
            "frames_total": record.get("frames_total"),
            "frames_ok": record.get("frames_ok"),
            "output_bytes": record.get("output_bytes"),
            "wall_clock_s": record.get("wall_clock_s"),
            "peak_rss_mb": record.get("peak_rss_mb"),
            "settings_json": json.dumps(record.get("settings") or {}),
            "summary_json": json.dumps(record.get("summary") or {}),
            "stages_json": json.dumps(record.get("stages") or []),
            "metrics_json": json.dumps(record.get("metrics") or {}),
            "output_json": json.dumps(record.get("output") or {}),
            "report_json": json.dumps(record.get("report") or {}),
            "artifacts_json": json.dumps(record.get("artifacts") or []),
            "error": record.get("error"),
        }
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (run_id, name, source, created_at, finished_at, status, profile,
                                  preset, frames_total, frames_ok, output_bytes, wall_clock_s,
                                  peak_rss_mb, settings_json, summary_json, stages_json,
                                  metrics_json, output_json, report_json, artifacts_json, error)
                VALUES (:run_id, :name, :source, :created_at, :finished_at, :status, :profile,
                        :preset, :frames_total, :frames_ok, :output_bytes, :wall_clock_s,
                        :peak_rss_mb, :settings_json, :summary_json, :stages_json,
                        :metrics_json, :output_json, :report_json, :artifacts_json, :error)
                ON CONFLICT(run_id) DO UPDATE SET
                    name=excluded.name, source=excluded.source, finished_at=excluded.finished_at,
                    status=excluded.status, profile=excluded.profile, preset=excluded.preset,
                    frames_total=excluded.frames_total, frames_ok=excluded.frames_ok,
                    output_bytes=excluded.output_bytes, wall_clock_s=excluded.wall_clock_s,
                    peak_rss_mb=excluded.peak_rss_mb, settings_json=excluded.settings_json,
                    summary_json=excluded.summary_json, stages_json=excluded.stages_json,
                    metrics_json=excluded.metrics_json, output_json=excluded.output_json,
                    report_json=excluded.report_json, artifacts_json=excluded.artifacts_json,
                    error=excluded.error
                """,
                row,
            )

    def delete_run(self, run_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            return cur.rowcount > 0

    # -- reads ------------------------------------------------------------
    def get_run(self, run_id: str, full: bool = True) -> dict | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row, full=full)

    def list_runs(self, limit: int = 100) -> list[dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_dict(r, full=False) for r in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row, full: bool) -> dict:
        d = {
            "run_id": row["run_id"],
            "name": row["name"],
            "source": row["source"],
            "created_at": row["created_at"],
            "finished_at": row["finished_at"],
            "status": row["status"],
            "profile": row["profile"],
            "preset": row["preset"],
            "frames_total": row["frames_total"],
            "frames_ok": row["frames_ok"],
            "output_bytes": row["output_bytes"],
            "wall_clock_s": row["wall_clock_s"],
            "peak_rss_mb": row["peak_rss_mb"],
            "error": row["error"],
            "summary": json.loads(row["summary_json"] or "{}"),
            "metrics": json.loads(row["metrics_json"] or "{}"),
            "output": json.loads(row["output_json"] or "{}"),
            "artifacts": json.loads(row["artifacts_json"] or "[]"),
        }
        if full:
            d["settings"] = json.loads(row["settings_json"] or "{}")
            d["stages"] = json.loads(row["stages_json"] or "[]")
            d["report"] = json.loads(row["report_json"] or "{}")
        else:
            stages = json.loads(row["stages_json"] or "[]")
            d["stages"] = stages
        return d

    # -- aggregate evidence ----------------------------------------------
    def performance_records(self, limit: int = 500) -> list[dict]:
        """One row per completed run with everything the Performance Lab plots.

        Only measured fields are returned; missing values stay ``None`` so the UI
        can render them as unavailable rather than as zero.
        """
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE status IN ('succeeded','failed') "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for row in rows:
            metrics = json.loads(row["metrics_json"] or "{}")
            output = json.loads(row["output_json"] or "{}")
            settings = json.loads(row["settings_json"] or "{}")
            summary = json.loads(row["summary_json"] or "{}")
            out.append(
                {
                    "run_id": row["run_id"],
                    "name": row["name"],
                    "created_at": row["created_at"],
                    "status": row["status"],
                    "profile": row["profile"],
                    "preset": row["preset"],
                    "source_kind": summary.get("source_kind"),
                    "frames_total": row["frames_total"],
                    "frames_accepted": row["frames_ok"],
                    "wall_clock_s": row["wall_clock_s"],
                    "peak_rss_mb": row["peak_rss_mb"],
                    "baseline_rss_mb": metrics.get("baseline_rss_mb"),
                    "peak_rss_delta_mb": metrics.get("peak_rss_delta_mb"),
                    "time_to_first_tile_s": metrics.get("time_to_first_tile_s"),
                    "throughput_fps": metrics.get("throughput_fps"),
                    "input_bytes": metrics.get("input_bytes"),
                    "output_bytes": row["output_bytes"],
                    "disk_read_bytes": metrics.get("disk_read_bytes"),
                    "disk_write_bytes": metrics.get("disk_write_bytes"),
                    "avg_cpu_percent": metrics.get("avg_cpu_percent"),
                    "peak_cpu_percent": metrics.get("peak_cpu_percent"),
                    "cpu_cores_effective": metrics.get("cpu_cores_effective"),
                    "pairs_candidates": metrics.get("pairs_candidates"),
                    "pairs_matched": metrics.get("pairs_matched"),
                    "pairs_failed": metrics.get("pairs_failed"),
                    "mean_inlier_ratio": metrics.get("mean_inlier_ratio"),
                    "mean_reprojection_error_px": metrics.get("mean_reprojection_error_px"),
                    "mean_gps_placement_error_m": metrics.get("mean_gps_placement_error_m"),
                    "frames_failed": metrics.get("frames_failed"),
                    "failure_count": metrics.get("frames_failed"),
                    "alignment_model": settings.get("alignment_model"),
                    "output_width": output.get("width"),
                    "output_height": output.get("height"),
                    "output_crs": output.get("crs"),
                    "output_kind": output.get("kind"),
                    "bandwidth": metrics.get("bandwidth") or {},
                    "profile_enforcement": metrics.get("profile_enforcement") or {},
                    "measurements_unavailable": metrics.get("measurements_unavailable") or [],
                    "run_groups": _run_groups(metrics),
                    "comparison": (json.loads(row["report_json"] or "{}") or {}).get(
                        "alignment_comparison"
                    ),
                }
            )
        return out

    # -- settings ---------------------------------------------------------
    def get_settings(self) -> dict:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}

    def put_settings(self, values: dict) -> dict:
        with self._lock, self._connect() as conn:
            for key, value in values.items():
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value)),
                )
        return self.get_settings()


def _run_groups(metrics: dict) -> dict:
    """Grouping keys used by the Performance Lab charts."""
    return {
        "profile": metrics.get("profile"),
        "detector": metrics.get("feature_detector"),
        "alignment_model": metrics.get("alignment_model"),
        "matching_megapixels": metrics.get("matching_megapixels"),
    }
