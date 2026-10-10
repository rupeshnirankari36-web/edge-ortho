"""Stage 10 - measure. Runtime, RSS, CPU and disk counters.

The brief requires measured values, not estimates:

    "Measure actual wall-clock processing time, peak process RSS where possible,
    frame counts, output bytes, and per-stage timing."
    "Mark unavailable measurements as unavailable."

Design notes:

* Everything is sampled from ``psutil`` on the *current process*, so the numbers
  describe this run on this machine and nothing else.
* Peak RSS is the maximum over a background sample loop; it is not inferred.
* Disk counters are deltas over the run; on platforms where ``psutil`` cannot
  read them the value is reported as unavailable instead of zero.
* CPU percent is normalised across the cores actually available to the process
  (after a profile's affinity is applied), so a pi-lite run is not reported as
  "25% of a 32-core machine" without context.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field

import psutil

# The exception type lives in profiles.py next to the limiter that raises it; importing
# it here means a caller needs one import for the whole memory-guard machinery.
from ..profiles import MemoryCeilingExceeded

MB = 1024 * 1024

__all__ = [
    "MemoryCeilingExceeded",
    "MemoryGuard",
    "ResourceSampler",
    "Sample",
    "stage_timer",
]


@dataclass
class Sample:
    t: float
    rss_mb: float
    cpu_percent: float


class ResourceSampler:
    """Background sampler for process RSS/CPU and system disk counters."""

    def __init__(self, interval_s: float = 0.1):
        self.interval_s = interval_s
        self._proc = psutil.Process()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.samples: list[Sample] = []
        self.baseline_rss_mb: float | None = None
        self.peak_rss_mb: float | None = None
        self.peak_cpu_percent: float | None = None
        self._disk0: tuple[int, int] | None = None
        self.disk_unavailable_reason: str | None = None
        self._t0 = 0.0

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        with suppress(Exception):
            self._proc.cpu_percent(None)  # prime the counter
        self.baseline_rss_mb = self.rss_mb()
        self.peak_rss_mb = self.baseline_rss_mb
        try:
            io = psutil.disk_io_counters()
            self._disk0 = (io.read_bytes, io.write_bytes) if io else None
            if io is None:
                self.disk_unavailable_reason = "psutil.disk_io_counters() returned nothing"
        except Exception as exc:
            self._disk0 = None
            self.disk_unavailable_reason = f"disk counters unavailable: {exc}"
        self._t0 = time.perf_counter()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._sample_once()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._sample_once()
            self._stop.wait(self.interval_s)

    def _sample_once(self) -> None:
        rss = self.rss_mb()
        try:
            cpu = self._proc.cpu_percent(None)
        except Exception:
            cpu = 0.0
        self.samples.append(Sample(time.perf_counter(), rss, cpu))
        self.peak_rss_mb = rss if self.peak_rss_mb is None else max(self.peak_rss_mb, rss)
        self.peak_cpu_percent = cpu if self.peak_cpu_percent is None else max(self.peak_cpu_percent, cpu)

    # -- accessors --------------------------------------------------------
    def rss_mb(self) -> float | None:
        with suppress(Exception):
            return self._proc.memory_info().rss / MB
        return None

    def stop_sample(self) -> None:
        with suppress(Exception):
            self._stop.set()

    @property
    def effective_cores(self) -> int:
        try:
            return len(self._proc.cpu_affinity())
        except Exception:
            return psutil.cpu_count(logical=True) or 1

    def cpu_summary(self) -> dict:
        """Peak/mean CPU as a percentage *per available core*.

        psutil reports process CPU relative to a single core, so dividing by the
        core count gives the machine utilisation, and both are reported.
        """
        cores = max(1, self.effective_cores)
        cpu_vals = [s.cpu_percent for s in self.samples]
        if not cpu_vals:
            return {"available": False}
        peak = max(cpu_vals)
        mean = sum(cpu_vals) / len(cpu_vals)
        return {
            "available": True,
            "cores_available_to_process": cores,
            "peak_percent_of_one_core": peak,
            "mean_percent_of_one_core": mean,
            "peak_percent_of_machine": peak / cores,
            "mean_percent_of_machine": mean / cores,
            "samples": len(cpu_vals),
        }

    def disk_summary(self) -> dict:
        if self._disk0 is None:
            return {"available": False, "reason": self.disk_unavailable_reason}
        try:
            io = psutil.disk_io_counters()
            if io is None:
                return {"available": False, "reason": "counters disappeared"}
            return {
                "available": True,
                "read_bytes": max(0, io.read_bytes - self._disk0[0]),
                "write_bytes": max(0, io.write_bytes - self._disk0[1]),
                "scope": "system-wide since boot, differenced across the run",
            }
        except Exception as exc:
            return {"available": False, "reason": str(exc)}

    def summary(self, elapsed_s: float | None = None) -> dict:
        rss = self.rss_mb()
        elapsed = elapsed_s if elapsed_s is not None else (time.perf_counter() - self._t0)
        deltas = [s.rss_mb - (self.baseline_rss_mb or 0) for s in self.samples]
        return {
            "elapsed_s": elapsed,
            "baseline_rss_mb": self.baseline_rss_mb,
            "peak_rss_mb": self.peak_rss_mb,
            "final_rss_mb": rss,
            "peak_rss_delta_mb": max(deltas) if deltas else None,
            "rss_samples": len(self.samples),
            "sampling_interval_s": self.interval_s,
            "cpu": self.cpu_summary(),
            "disk": self.disk_summary(),
        }


@contextmanager
def stage_timer():
    """Wall-clock timer for one pipeline stage using perf_counter."""
    box = {"elapsed_s": None, "started": time.perf_counter()}
    try:
        yield box
    finally:
        box["elapsed_s"] = time.perf_counter() - box["started"]


@dataclass
class MemoryGuard:
    """Soft RAM ceiling for a constrained profile.

    ``check()`` is called from the compose loop, so a run that would exceed the
    profile's limit stops quickly with a clear error instead of being paged out
    for an hour. This is a *behavioural* limit, not a cgroup: the run report
    states that plainly.
    """

    limit_mb: int | None
    sampler: ResourceSampler
    profile_name: str = "laptop"
    exceeded: bool = False
    peak_seen_mb: float | None = None
    messages: list[str] = field(default_factory=list)

    def check(self) -> None:
        if self.limit_mb is None:
            return
        rss = self.sampler.rss_mb()
        if rss is None:
            return
        self.peak_seen_mb = rss if self.peak_seen_mb is None else max(self.peak_seen_mb, rss)
        if rss > self.limit_mb:
            self.exceeded = True
            raise MemoryCeilingExceeded(
                f"profile {self.profile_name!r} RAM ceiling of {self.limit_mb} MB exceeded "
                f"(process RSS {rss:.0f} MB). Reduce the output pixel cap, use a coarser "
                f"matching resolution, or run the laptop profile."
            )



