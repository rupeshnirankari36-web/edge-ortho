"""Telemetry data structures and metrics aggregator."""

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class MetricSample:
    timestamp: float
    elapsed_seconds: float
    stage: str
    cpu_percent: float
    rss_ram_mb: float
    disk_read_mb: float
    disk_write_mb: float


@dataclass
class StageTiming:
    stage_name: str
    start_time: float
    end_time: float | None = None
    duration_seconds: float | None = None


@dataclass
class RunSummary:
    run_id: str
    profile: str
    preset: str
    dataset_name: str
    total_frames_found: int = 0
    frames_accepted: int = 0
    frames_rejected: int = 0
    total_matches_evaluated: int = 0
    total_inliers_found: int = 0
    mean_inlier_ratio: float = 0.0
    mean_reprojection_error: float = 0.0
    total_latency_seconds: float = 0.0
    time_to_first_tile_seconds: float | None = None
    peak_rss_ram_mb: float = 0.0
    avg_cpu_percent: float = 0.0
    total_disk_read_mb: float = 0.0
    total_disk_write_mb: float = 0.0
    output_geotiff_bytes: int = 0
    output_cog_bytes: int = 0
    input_bytes: int = 0
    bandwidth_reduction_factor: float = 0.0
    stages: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def save_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)


def save_samples_to_csv(samples: list[MetricSample], path: Path) -> None:
    """Exports time-series resource samples to CSV for graph generation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not samples:
        return

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "timestamp",
                "elapsed_seconds",
                "stage",
                "cpu_percent",
                "rss_ram_mb",
                "disk_read_mb",
                "disk_write_mb",
            ],
        )
        writer.writeheader()
        for s in samples:
            writer.writerow(asdict(s))
