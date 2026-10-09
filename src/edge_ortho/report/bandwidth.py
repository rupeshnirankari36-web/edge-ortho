"""Bandwidth transfer calculations and motivation report table."""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass
class BandwidthScenario:
    bandwidth_mbps: float
    raw_upload_seconds: float
    ortho_upload_seconds: float
    time_saved_seconds: float
    savings_percent: float


def compute_transfer_seconds(total_bytes: int, bandwidth_mbps: float) -> float:
    """Calculates transfer duration: transfer_seconds = bytes * 8 / (bandwidth_mbps * 1e6)."""
    if bandwidth_mbps <= 0:
        return 0.0
    bits = total_bytes * 8.0
    return bits / (bandwidth_mbps * 1_000_000.0)


def generate_bandwidth_scenarios(
    raw_input_bytes: int,
    output_mosaic_bytes: int,
    speeds_mbps: Sequence[float] = (1.0, 5.0, 20.0),
) -> list[BandwidthScenario]:
    """Generates comparison table across bandwidth constraints."""
    scenarios = []
    for mbps in speeds_mbps:
        raw_sec = compute_transfer_seconds(raw_input_bytes, mbps)
        ortho_sec = compute_transfer_seconds(output_mosaic_bytes, mbps)
        saved_sec = max(0.0, raw_sec - ortho_sec)
        pct = (saved_sec / raw_sec * 100.0) if raw_sec > 0 else 0.0

        scenarios.append(
            BandwidthScenario(
                bandwidth_mbps=mbps,
                raw_upload_seconds=raw_sec,
                ortho_upload_seconds=ortho_sec,
                time_saved_seconds=saved_sec,
                savings_percent=pct,
            )
        )
    return scenarios


def format_seconds(sec: float) -> str:
    """Human-readable time string (e.g. '12m 34s' or '1h 05m')."""
    if sec < 60:
        return f"{sec:.1f}s"
    elif sec < 3600:
        mins = int(sec // 60)
        rem_sec = int(sec % 60)
        return f"{mins}m {rem_sec:02d}s"
    else:
        hrs = int(sec // 3600)
        mins = int((sec % 3600) // 60)
        return f"{hrs}h {mins:02d}m"
