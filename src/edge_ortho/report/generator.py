"""Executive report and charts generation."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # Non-interactive headless backend
import matplotlib.pyplot as plt

from ..monitor.metrics import MetricSample, RunSummary
from .bandwidth import format_seconds, generate_bandwidth_scenarios


def generate_resource_chart(
    samples: list[MetricSample],
    output_png_path: Path,
    title: str = "Edge Pipeline Resource Consumption",
) -> None:
    """Plots CPU % and RAM (MB) against elapsed time with pipeline stage transitions."""
    if not samples:
        return

    output_png_path.parent.mkdir(parents=True, exist_ok=True)

    times = [s.elapsed_seconds for s in samples]
    cpu = [s.cpu_percent for s in samples]
    ram = [s.rss_ram_mb for s in samples]

    fig, ax1 = plt.subplots(figsize=(10, 5), dpi=150)

    color_ram = "#1f77b4"
    ax1.set_xlabel("Elapsed Time (seconds)", fontsize=11, fontweight="bold")
    ax1.set_ylabel("RSS Memory (MB)", color=color_ram, fontsize=11, fontweight="bold")
    ax1.plot(times, ram, color=color_ram, linewidth=2, label="RSS RAM (MB)")
    ax1.tick_params(axis="y", labelcolor=color_ram)
    ax1.grid(True, linestyle="--", alpha=0.5)

    ax2 = ax1.twinx()
    color_cpu = "#ff7f0e"
    ax2.set_ylabel("Process CPU (%)", color=color_cpu, fontsize=11, fontweight="bold")
    ax2.plot(times, cpu, color=color_cpu, linewidth=1.5, alpha=0.85, label="CPU (%)")
    ax2.tick_params(axis="y", labelcolor=color_cpu)

    plt.title(title, fontsize=13, fontweight="bold", pad=12)
    fig.tight_layout()
    plt.savefig(output_png_path)
    plt.close(fig)


def build_markdown_report(
    summary: RunSummary,
    output_md_path: Path,
) -> str:
    """Generates the integrated markdown evaluation report."""
    output_md_path.parent.mkdir(parents=True, exist_ok=True)

    bandwidth_table = generate_bandwidth_scenarios(
        summary.input_bytes,
        summary.output_cog_bytes or summary.output_geotiff_bytes,
    )

    lines = [
        f"# Edge-Ortho Execution Report — Run `{summary.run_id}`",
        "",
        f"**Profile:** `{summary.profile}` | **Preset:** `{summary.preset}` | **Dataset:** `{summary.dataset_name}`  ",
        f"**Date:** {summary.metadata.get('timestamp', 'N/A')} | **System:** {summary.metadata.get('platform', 'N/A')}  ",
        "",
        "---",
        "",
        "## 1. Executive Performance Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| **Frames Processed / Accepted** | {summary.frames_accepted} / {summary.total_frames_found} |",
        f"| **Frames Rejected** | {summary.frames_rejected} |",
        f"| **Total Pipeline Latency** | {summary.total_latency_seconds:.2f} s |",
        f"| **Time-to-First-Tile** | {f'{summary.time_to_first_tile_seconds:.2f} s' if summary.time_to_first_tile_seconds else 'N/A'} |",
        f"| **Throughput** | {(summary.frames_accepted / max(summary.total_latency_seconds, 0.001)):.2f} frames/sec |",
        f"| **Peak RSS RAM** | **{summary.peak_rss_ram_mb:.1f} MB** |",
        f"| **Average CPU Utilization** | {summary.avg_cpu_percent:.1f}% |",
        f"| **Mean Feature Inliers / Pair** | {summary.mean_inlier_ratio * 100.0:.1f}% |",
        f"| **Mean Reprojection RMSE** | {summary.mean_reprojection_error:.2f} px |",
        f"| **Input Imagery Size** | {summary.input_bytes / (1024 * 1024):.2f} MB |",
        f"| **Output Orthomosaic Size** | {summary.output_geotiff_bytes / (1024 * 1024):.2f} MB |",
        f"| **Bandwidth Reduction Factor** | **{summary.bandwidth_reduction_factor:.1f}x** |",
        "",
        "---",
        "",
        "## 2. Stage-by-Stage Latency Breakdown",
        "",
        "| Pipeline Stage | Duration (s) | Share (%) |",
        "|---|---:|---:|",
    ]

    tot = max(summary.total_latency_seconds, 0.001)
    for st, dur in summary.stages.items():
        pct = (dur / tot) * 100.0
        lines.append(f"| `{st}` | {dur:.2f} s | {pct:.1f}% |")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 3. Edge Bandwidth Transfer Motivation",
            "",
            "Comparing transmission of raw unstitched drone captures versus the single edge-processed orthomosaic:",
            "",
            "| Uplink Bandwidth | Raw Upload Time | Orthomosaic Upload Time | Time Saved | Bandwidth Saved |",
            "|---|---:|---:|---:|---:|",
        ]
    )

    for row in bandwidth_table:
        lines.append(
            f"| **{row.bandwidth_mbps:.0f} Mbps** | "
            f"{format_seconds(row.raw_upload_seconds)} | "
            f"{format_seconds(row.ortho_upload_seconds)} | "
            f"{format_seconds(row.time_saved_seconds)} | "
            f"{row.savings_percent:.1f}% |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 4. Hardware Emulation & Claims Note",
            "",
            "> **Notice on Hardware Limits:** When executed under local virtual environment or Docker profiles (`pi-lite`, `pi-class`, `jetson-class`), resource caps emulate CPU core allocation and memory ceilings. Host-specific clock rates and bus memory speeds differ from physical ARM SOCs.",
            "",
            "---",
            "",
            "## 5. Artifacts and Web Viewers",
            "",
            "- **GeoTIFF:** `orthomosaic.tif`",
            "- **Cloud Optimized GeoTIFF:** `orthomosaic.cog.tif`",
            "- **XYZ Web Map Tiles:** `tiles/{z}/{x}/{y}.png`",
            "- **Leaflet Interactive Viewer:** `viewer/leaflet/index.html?manifest=../../outputs/manifest.json`",
            "- **Mapbox GL JS Viewer:** `viewer/mapbox/index.html?manifest=../../outputs/manifest.json`",
            "- **Resource Telemetry Plot:** `resources.png`",
            "",
        ]
    )

    report_content = "\n".join(lines)
    with open(output_md_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    return report_content
