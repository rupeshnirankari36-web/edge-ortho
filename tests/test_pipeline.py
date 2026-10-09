"""End-to-end pipeline integration test."""

from pathlib import Path

import rasterio

from edge_ortho.config import build_pipeline_config
from edge_ortho.pipeline import run_pipeline


def test_full_pipeline_end_to_end(synthetic_survey: Path, tmp_path: Path):
    out_dir = tmp_path / "survey_output"
    cfg = build_pipeline_config(
        profile_name="laptop",
        preset_name="fast",
        overrides={
            "matcher": "orb",
            "transform_model": "affine",
            "tile_size": 512,
            "generate_cog": True,
            "generate_tiles": True,
        },
    )

    summary = run_pipeline(
        input_dir=synthetic_survey,
        output_dir=out_dir,
        config=cfg,
    )

    assert summary.frames_accepted == 6
    assert summary.total_latency_seconds > 0.0
    assert summary.peak_rss_ram_mb > 0.0

    # Verify GeoTIFF output
    geotiff_path = out_dir / "orthomosaic.tif"
    assert geotiff_path.exists()

    with rasterio.open(geotiff_path) as ds:
        assert ds.count == 4  # RGBA
        assert ds.crs.to_epsg() == 32611
        assert ds.width > 200
        assert ds.height > 200

    # Verify reports and artifacts
    assert (out_dir / "orthomosaic_cog.tif").exists()
    assert (out_dir / "report.md").exists()
    assert (out_dir / "report.json").exists()
    assert (out_dir / "metrics.json").exists()
    assert (out_dir / "metrics.csv").exists()
    assert (out_dir / "resources.png").exists()
    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "tiles").exists()
