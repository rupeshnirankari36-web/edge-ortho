import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from edge_ortho.geo_export import convert_to_cog
from edge_ortho.phase2 import (
    CanvasSpec,
    build_phase2_manifest,
    compose_to_geotiff,
    generate_xyz_tiles,
    load_canvas_contract,
    load_pose_contract,
    write_phase2_manifest,
)


def test_contracts_are_loaded_from_public_json_files(tmp_path: Path):
    (tmp_path / "poses.json").write_text(json.dumps({"poses": [{"frame_id": "a", "x": 10, "y": 20, "confidence": 0.9}]}))
    (tmp_path / "canvas.json").write_text(json.dumps({"crs": "EPSG:32643", "left": 500000, "top": 2100000, "pixel_size": 1, "width": 64, "height": 48, "gsd": 1, "source_dataset": "fixture"}))
    poses = load_pose_contract(tmp_path / "poses.json")
    canvas = load_canvas_contract(tmp_path / "canvas.json")
    assert poses[0].frame_id == "a"
    assert canvas.transform.e == -1
    assert canvas.width == 64


def test_composition_is_windowed_and_emits_first_and_final_events(tmp_path: Path):
    canvas = CanvasSpec("EPSG:32643", 500000, 2100000, 1, 64, 48, 1, "fixture")
    events = []

    def render(window, _canvas):
        result = np.zeros((4, int(window.height), int(window.width)), dtype=np.uint8)
        result[0] = 255
        result[3] = 255
        return result

    tif, emitted = compose_to_geotiff(canvas, tmp_path / "orthomosaic.tif", render, tile_size=32, on_event=events.append)
    assert emitted[0]["event"] == "first_tile"
    assert emitted[-1]["event"] == "final_output"
    assert len([e for e in emitted if e["event"] in {"first_tile", "tile_written"}]) == 4
    assert events == emitted
    with rasterio.open(tif) as src:
        assert src.width == 64 and src.height == 48
        assert src.crs.to_epsg() == 32643
        assert src.read(1).max() == 255


def test_xyz_tiles_and_manifest_report_actual_outputs(tmp_path: Path):
    canvas = CanvasSpec("EPSG:4326", 73.0, 19.2, 0.001, 64, 64, 0.001, "fixture")

    def render(window, _canvas):
        result = np.zeros((4, int(window.height), int(window.width)), dtype=np.uint8)
        result[1] = 100
        result[3] = 255
        return result

    tif, _ = compose_to_geotiff(canvas, tmp_path / "orthomosaic.tif", render, tile_size=32)
    cog = convert_to_cog(tif, tmp_path / "orthomosaic_cog.tif")
    tile_report = generate_xyz_tiles(tif, tmp_path / "tiles", zoom_min=12, zoom_max=12)
    assert tile_report["tile_count"] > 0
    assert tile_report["tile_bytes"] > 0
    assert list((tmp_path / "tiles").rglob("*.png"))
    manifest = build_phase2_manifest(tif, dataset="fixture", source="synthetic", cog_path=cog, tile_report=tile_report, run_id="run-1")
    assert manifest["cog_bytes"] > 0
    assert manifest["tiles"]["tile_count"] == tile_report["tile_count"]
    path = write_phase2_manifest(manifest, tmp_path / "manifest.json")
    assert json.loads(path.read_text())["run_id"] == "run-1"
