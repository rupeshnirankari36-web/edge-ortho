"""Command line interface for edge-ortho."""

import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .align import compare_models_on_pair
from .config import build_pipeline_config
from .features import extract_features_from_image, get_feature_detector, match_feature_pair
from .ingest import ingest_and_validate_directory
from .pipeline import run_pipeline

app = typer.Typer(
    name="edge-ortho",
    help="Edge-optimized 2D drone orthomosaic pipeline for constrained devices.",
    add_completion=False,
)
console = Console()


@app.command()
def run(
    input: Path = typer.Option(
        ..., "--input", "-i", help="Path to directory containing drone images"
    ),
    out: Path = typer.Option(
        ..., "--out", "-o", help="Output directory for orthomosaic and reports"
    ),
    profile: str = typer.Option(
        "pi-class",
        "--profile",
        "-p",
        help="Hardware profile (pi-lite, pi-class, jetson-class, laptop)",
    ),
    preset: str = typer.Option(
        "balanced", "--preset", help="Quality preset (fast, balanced, quality)"
    ),
    matcher: str | None = typer.Option(
        None, "--matcher", "-m", help="Feature matcher override (orb, akaze, sift)"
    ),
    model: str | None = typer.Option(
        None, "--model", help="Transform model override (similarity, affine, homography)"
    ),
    no_cog: bool = typer.Option(False, "--no-cog", help="Disable COG generation"),
    no_tiles: bool = typer.Option(False, "--no-tiles", help="Disable XYZ tile generation"),
):
    """Executes the edge-optimized 2D orthomosaic pipeline on an image folder."""
    console.print("[bold cyan]▶ Starting edge-ortho pipeline[/bold cyan]")
    console.print(f"  Input:   [yellow]{input}[/yellow]")
    console.print(f"  Output:  [yellow]{out}[/yellow]")
    console.print(f"  Profile: [green]{profile}[/green] | Preset: [green]{preset}[/green]")

    overrides = {}
    if matcher:
        overrides["matcher"] = matcher
    if model:
        overrides["transform_model"] = model
    if no_cog:
        overrides["generate_cog"] = False
    if no_tiles:
        overrides["generate_tiles"] = False

    config = build_pipeline_config(
        profile_name=profile,
        preset_name=preset,
        overrides=overrides,
    )

    t0 = time.perf_counter()
    summary = run_pipeline(input_dir=input, output_dir=out, config=config)
    elapsed = time.perf_counter() - t0

    table = Table(title="Pipeline Execution Summary", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="dim")
    table.add_column("Result", style="bold green")

    table.add_row("Frames Accepted", f"{summary.frames_accepted} / {summary.total_frames_found}")
    table.add_row("Total Latency", f"{elapsed:.2f} s")
    if summary.time_to_first_tile_seconds:
        table.add_row("Time to First Tile", f"{summary.time_to_first_tile_seconds:.2f} s")
    table.add_row("Peak RAM", f"{summary.peak_rss_ram_mb:.1f} MB")
    table.add_row("Reprojection RMSE", f"{summary.mean_reprojection_error:.2f} px")
    table.add_row("Bandwidth Reduction", f"{summary.bandwidth_reduction_factor:.1f}x")
    table.add_row("GeoTIFF Output", str(out / "orthomosaic.tif"))
    if summary.output_cog_bytes:
        table.add_row("COG Output", str(out / "orthomosaic.cog.tif"))
    table.add_row("Executive Report", str(out / "report.md"))

    console.print(table)
    console.print("[bold green]✔ Orthomosaic generation completed successfully![/bold green]")


@app.command()
def watch(
    input: Path = typer.Option(
        ..., "--input", "-i", help="Directory to monitor for incoming drone frames"
    ),
    out: Path = typer.Option(
        ..., "--out", "-o", help="Output directory for orthomosaic and reports"
    ),
    profile: str = typer.Option("pi-class", "--profile", "-p", help="Hardware profile"),
    preset: str = typer.Option("balanced", "--preset", help="Quality preset"),
    settle_seconds: float = typer.Option(
        5.0, "--settle", help="Seconds of inactivity before triggering pipeline"
    ),
):
    """Watches a directory for new drone frames and triggers the pipeline once transmission settles."""
    console.print(
        f"[bold cyan]👀 Watching directory: {input}[/bold cyan] (Settle timeout: {settle_seconds}s)"
    )
    last_count = 0
    stable_cycles = 0

    try:
        while True:
            files = list(input.glob("*.[jJ][pP][gG]")) + list(input.glob("*.[jJ][pP][eE][gG]"))
            current_count = len(files)

            if current_count > 0 and current_count == last_count:
                stable_cycles += 1
                if stable_cycles >= int(settle_seconds):
                    console.print(
                        f"\n[green]⚡ Detected stable set of {current_count} images. Launching pipeline...[/green]"
                    )
                    config = build_pipeline_config(profile_name=profile, preset_name=preset)
                    run_pipeline(input_dir=input, output_dir=out, config=config)
                    console.print("[green]Waiting for new incoming images...[/green]")
                    stable_cycles = 0
            else:
                stable_cycles = 0
                last_count = current_count

            time.sleep(1.0)
    except KeyboardInterrupt:
        console.print("\n[yellow]Watch mode stopped by user.[/yellow]")


@app.command("verify-dataset")
def verify_dataset(
    dataset_path: Path = typer.Argument(..., help="Path to raw image folder to inspect"),
    csv_out: Path | None = typer.Option(None, "--csv", help="Optional metadata CSV output path"),
):
    """Inspects dataset EXIF tags, GPS coverage, and verifies acceptance rules."""
    console.print(f"[bold cyan]Auditing dataset: {dataset_path}[/bold cyan]")
    report = ingest_and_validate_directory(dataset_path)

    table = Table(title="Dataset Acceptance Audit", show_header=True)
    table.add_column("Criterion", style="dim")
    table.add_column("Count / Status", style="bold")

    table.add_row("Total Files Discovered", str(report.total_found))
    table.add_row("Accepted Geotagged Frames", f"[green]{report.accepted_count}[/green]")
    table.add_row("Rejected Files", f"[red]{report.rejected_count}[/red]")

    console.print(table)

    if report.rejections:
        console.print("\n[bold red]Rejection Reasons:[/bold red]")
        for rej in report.rejections[:10]:
            console.print(f"  • {rej['file']}: {rej['reason']}")
        if len(report.rejections) > 10:
            console.print(f"  ... and {len(report.rejections) - 10} more.")

    if csv_out and report.records:
        import csv

        csv_out.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_out, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "frame_id",
                    "lat",
                    "lon",
                    "altitude",
                    "yaw",
                    "pitch",
                    "focal_length",
                    "width",
                    "height",
                ]
            )
            for r in report.records:
                writer.writerow(
                    [
                        r.frame_id,
                        r.lat,
                        r.lon,
                        r.altitude,
                        r.yaw,
                        r.pitch,
                        r.focal_length,
                        r.width,
                        r.height,
                    ]
                )
        console.print(f"[green]Audit CSV saved to: {csv_out}[/green]")


@app.command("compare-transforms")
def compare_transforms(
    image1: Path = typer.Argument(..., help="Path to first image"),
    image2: Path = typer.Argument(..., help="Path to second image"),
    matcher_name: str = typer.Option(
        "akaze", "--matcher", help="Matcher to use (orb, akaze, sift)"
    ),
):
    """Directly compares Affine vs Homography RANSAC alignment on an image pair."""
    console.print(
        f"[cyan]Comparing Affine vs Homography on pair:[/cyan]\n  1: {image1}\n  2: {image2}"
    )

    detector = get_feature_detector(matcher_name)
    f1 = extract_features_from_image(image1, image1.stem, detector)
    f2 = extract_features_from_image(image2, image2.stem, detector)

    if not f1 or not f2:
        console.print("[red]Failed to extract keypoints from one or both images.[/red]")
        return

    matched = match_feature_pair(f1, f2)
    if not matched:
        console.print("[red]No valid feature matches found between images.[/red]")
        return

    comp = compare_models_on_pair(image1.stem, image2.stem, matched.src_points, matched.tgt_points)

    table = Table(title="Model Comparison", show_header=True)
    table.add_column("Property")
    table.add_column("Affine Model", style="green")
    table.add_column("Homography Model", style="yellow")

    table.add_row("Status", comp.affine.status, comp.homography.status)
    table.add_row("Inliers", str(comp.affine.num_inliers), str(comp.homography.num_inliers))
    table.add_row(
        "Inlier Ratio",
        f"{comp.affine.inlier_ratio * 100:.1f}%",
        f"{comp.homography.inlier_ratio * 100:.1f}%",
    )
    table.add_row(
        "Reprojection RMSE",
        f"{comp.affine.reprojection_error:.2f} px",
        f"{comp.homography.reprojection_error:.2f} px",
    )
    table.add_row("Runtime", f"{comp.affine_time_ms:.1f} ms", f"{comp.homography_time_ms:.1f} ms")

    console.print(table)
    console.print(
        f"[bold cyan]Recommended Model:[/bold cyan] [bold green]{comp.winner.upper()}[/bold green] ({comp.reason})"
    )


def main():
    app()


if __name__ == "__main__":
    main()
