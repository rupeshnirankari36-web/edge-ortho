"""Background resource sampler measuring CPU, RSS RAM, and disk I/O with psutil."""

import threading
import time

import psutil

from .metrics import MetricSample, StageTiming


class ResourceMonitor:
    """Threaded system resource monitor tracking edge hardware metrics during execution."""

    def __init__(self, sample_interval_sec: float = 0.5):
        self.interval = sample_interval_sec
        self.samples: list[MetricSample] = []
        self.stages: dict[str, StageTiming] = {}
        self.current_stage: str = "init"
        self._running = False
        self._thread: threading.Thread | None = None
        self._start_time = 0.0
        self._process = psutil.Process()
        self._initial_disk_io = None
        self.time_to_first_tile: float | None = None

    def start(self) -> None:
        """Starts background sampling."""
        self._start_time = time.perf_counter()
        try:
            self._initial_disk_io = psutil.disk_io_counters()
        except Exception:
            self._initial_disk_io = None

        self._running = True
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def set_stage(self, stage_name: str) -> None:
        """Transitions to next pipeline stage, recording duration."""
        now = time.perf_counter()
        if self.current_stage in self.stages:
            st = self.stages[self.current_stage]
            st.end_time = now
            st.duration_seconds = now - st.start_time

        self.current_stage = stage_name
        self.stages[stage_name] = StageTiming(
            stage_name=stage_name,
            start_time=now,
        )

    def record_first_tile(self) -> None:
        """Marks timestamp when first composited tile was completed."""
        if self.time_to_first_tile is None:
            self.time_to_first_tile = time.perf_counter() - self._start_time

    def stop(self) -> None:
        """Stops background monitor."""
        now = time.perf_counter()
        if self.current_stage in self.stages:
            st = self.stages[self.current_stage]
            st.end_time = now
            st.duration_seconds = now - st.start_time

        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _sample_loop(self) -> None:
        while self._running:
            try:
                now = time.perf_counter()
                elapsed = now - self._start_time

                # CPU percent of current process
                cpu = self._process.cpu_percent(interval=None)
                # RSS memory in MB
                mem_info = self._process.memory_info()
                rss_mb = mem_info.rss / (1024.0 * 1024.0)

                # Disk I/O delta
                read_mb = 0.0
                write_mb = 0.0
                if self._initial_disk_io:
                    try:
                        current_io = psutil.disk_io_counters()
                        read_mb = (current_io.read_bytes - self._initial_disk_io.read_bytes) / (
                            1024.0 * 1024.0
                        )
                        write_mb = (current_io.write_bytes - self._initial_disk_io.write_bytes) / (
                            1024.0 * 1024.0
                        )
                    except Exception:
                        pass

                self.samples.append(
                    MetricSample(
                        timestamp=now,
                        elapsed_seconds=elapsed,
                        stage=self.current_stage,
                        cpu_percent=cpu,
                        rss_ram_mb=rss_mb,
                        disk_read_mb=read_mb,
                        disk_write_mb=write_mb,
                    )
                )
            except Exception:
                pass

            time.sleep(self.interval)

    def get_peak_ram_mb(self) -> float:
        if not self.samples:
            return 0.0
        return max(s.rss_ram_mb for s in self.samples)

    def get_avg_cpu_percent(self) -> float:
        if not self.samples:
            return 0.0
        return sum(s.cpu_percent for s in self.samples) / len(self.samples)

    def get_stage_durations(self) -> dict[str, float]:
        return {
            name: (st.duration_seconds if st.duration_seconds is not None else 0.0)
            for name, st in self.stages.items()
        }
