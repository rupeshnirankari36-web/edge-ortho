"""Bridge between Rupesh Phase 2 events and Naman telemetry/reporting."""
from __future__ import annotations

import datetime
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..report.generator import build_markdown_report, generate_resource_chart
from .metrics import RunSummary, save_samples_to_csv
from .sampler import ResourceMonitor


@dataclass
class Phase2MetricsBridge:
    """Collect metrics without importing CV or raster implementation classes."""

    run_id: str
    dataset_name: str
    profile: str
    preset: str
    output_dir: Path
    sample_interval_sec: float = 0.5

    def __post_init__(self) -> None:
        self.output_dir = Path(self.output_dir)
        self.monitor = ResourceMonitor(sample_interval_sec=self.sample_interval_sec)
        self.tile_events: list[dict[str, Any]] = []
        self._started = False
        self._started_at = 0.0

    def start(self) -> None:
        if self._started:
            raise RuntimeError("metrics bridge already started")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.monitor.start()
        self._started_at = time.perf_counter()
        self._started = True

    def set_stage(self, stage_name: str) -> None:
        if not self._started:
            raise RuntimeError("start the metrics bridge before setting a stage")
        self.monitor.set_stage(stage_name)

    def handle_phase2_event(self, event: dict[str, Any]) -> None:
        """Consume the JSON-compatible events emitted by phase2.compose_to_geotiff."""
        if not self._started:
            raise RuntimeError("start the metrics bridge before handling events")
        event_copy = dict(event)
        self.tile_events.append(event_copy)
        if event_copy.get("event") == "first_tile":
            self.monitor.record_first_tile()

    def finalize(
        self,
        *,
        input_bytes: int,
        geotiff_bytes: int,
        cog_bytes: int = 0,
    ) -> RunSummary:
        if not self._started:
            raise RuntimeError("start the metrics bridge before finalizing")
        self.monitor.stop()
        total_latency = max(0.0, time.perf_counter() - self._started_at)
        output_bytes = cog_bytes or geotiff_bytes
        summary = RunSummary(
            run_id=self.run_id,
            profile=self.profile,
            preset=self.preset,
            dataset_name=self.dataset_name,
            total_latency_seconds=total_latency,
            time_to_first_tile_seconds=self.monitor.time_to_first_tile,
            peak_rss_ram_mb=self.monitor.get_peak_ram_mb(),
            avg_cpu_percent=self.monitor.get_avg_cpu_percent(),
            output_geotiff_bytes=geotiff_bytes,
            output_cog_bytes=cog_bytes,
            input_bytes=input_bytes,
            bandwidth_reduction_factor=(input_bytes / output_bytes) if output_bytes else 0.0,
            stages=self.monitor.get_stage_durations(),
            metadata={
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
                "python": platform.python_version(),
                "phase2_tile_events": str(len(self.tile_events)),
            },
        )
        save_samples_to_csv(self.monitor.samples, self.output_dir / "metrics.csv")
        summary.save_json(self.output_dir / "metrics.json")
        generate_resource_chart(self.monitor.samples, self.output_dir / "resources.png", title=f"Edge Ortho: {self.dataset_name}")
        build_markdown_report(summary, self.output_dir / "report.md")
        return summary
