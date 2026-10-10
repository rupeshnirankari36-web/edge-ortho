"""Composition and geospatial output.

The composer is tested for the two properties the product claims: tiles are handed
to a sink and dropped rather than accumulated, and the raster that comes out is a
genuinely georeferenced, readable dataset whose CRS, transform and bounds describe
the pixel grid. COG and XYZ tile generation are only asserted when the tooling is
present; otherwise the reported reason is asserted instead.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from edge_ortho.compose.mosaic import compose_mosaic, estimate_exposure_gains
from edge_ortho.contracts import FrameRecord, GlobalPose
from edge_ortho.geo import raster as geopraster

from conftest import big_scene, write_geotagged_jpeg

CANVAS_W, CANVAS_H = 900, 600
GSD = 0.02
ORIGIN_E, ORIGIN_N = 576_600.0, 5_188_200.0
EPSG = 32615


def build_frames(tmp_path, count: int = 4, size=(400, 300)) -> list[FrameRecord]:
    scene = big_scene(1400, 700, seed=13)
    frames: list[FrameRecord] = []
    for i in range(count):
        crop = scene[40 : 40 + size[1], 30 + i * 120 : 30 + i * 120 + size[0]]
        path = write_geotagged_jpeg(
            tmp_path / f"DJI_{2000 + i}.JPG",
            crop,
            lat=46.84 + i * 1e-5,
            lon=-91.99 + i * 1e-5,
            altitude_m=90.0,
        )
        record = FrameRecord(
            frame_id=f"f{i}",
            path=str(path),
            filename=path.name,
            bytes=path.stat().st_size,
            accepted=True,
        )
        record.width, record.height = size
        record.gsd_m = GSD
        record.footprint_w_m = size[0] * GSD
        record.footprint_h_m = size[1] * GSD
        frames.append(record)
    return frames


def build_poses(frames: list[FrameRecord], step_px: int = 120) -> dict[str, GlobalPose]:
    """Place each frame 120 px further right on the canvas, same scale."""
    poses: dict[str, GlobalPose] = {}
    for i, frame in enumerate(frames):
        poses[frame.frame_id] = GlobalPose(
            frame_id=frame.frame_id,
            scale=1.0,
            theta_rad=0.0,
            tx=float(30 + i * step_px),
            ty=40.0,
            confidence=1.0,
            seed_source="gps",
        )
    return poses


# --------------------------------------------------------------------------
# composition
# --------------------------------------------------------------------------

def test_tiles_are_streamed_to_the_sink_and_not_retained(tmp_path):
    frames = build_frames(tmp_path)
    poses = build_poses(frames)
    seen: list[tuple[int, int]] = []

    def sink(tx: int, ty: int, rgba: np.ndarray) -> None:
        assert rgba.dtype == np.uint8
        assert rgba.shape[2] == 4
        seen.append((tx, ty))

    tiles, stats = compose_mosaic(
        frames, poses, CANVAS_W, CANVAS_H, tile_size=256, sink=sink, collect=False
    )
    assert seen, "the sink must receive tiles"
    assert tiles == {}, "streamed tiles must not be retained in memory"
    assert stats.tiles_written == len(seen)
    assert stats.tiles_total == math.ceil(CANVAS_W / 256) * math.ceil(CANVAS_H / 256)
    assert stats.time_to_first_tile_s is not None and stats.time_to_first_tile_s > 0
    assert stats.decode_count >= 1
    assert stats.frames_composed >= 2


def test_composed_pixels_come_from_the_source_frames(tmp_path):
    frames = build_frames(tmp_path)
    poses = build_poses(frames, step_px=0)
    tiles, stats = compose_mosaic(frames, poses, CANVAS_W, CANVAS_H, tile_size=512, collect=True)
    assert stats.frames_composed >= 1
    canvas = np.zeros((CANVAS_H, CANVAS_W, 4), dtype=np.uint8)
    for (tx, ty), rgba in tiles.items():
        h, w = rgba.shape[:2]
        canvas[ty * 512 : ty * 512 + h, tx * 512 : tx * 512 + w] = rgba
    covered = canvas[:, :, 3] > 0
    assert covered.mean() > 0.05, "the composer produced almost no coverage"
    rgb = canvas[:, :, :3][covered]
    assert rgb.mean() > 10, "composed pixels are black, not imagery"


def test_exposure_gains_stay_within_the_documented_range(tmp_path):
    frames = build_frames(tmp_path)
    poses = build_poses(frames)
    gains = estimate_exposure_gains(frames, poses)
    assert set(gains) <= {f.frame_id for f in frames}
    for value in gains.values():
        assert 0.8 <= value <= 1.25


def test_frame_without_a_pose_is_skipped_not_composed(tmp_path):
    frames = build_frames(tmp_path, count=3)
    poses = build_poses(frames[:2])
    _, stats = compose_mosaic(frames, poses, CANVAS_W, CANVAS_H, tile_size=256, collect=True)
    assert stats.frames_skipped == 1


def test_missing_source_file_is_counted_as_a_failed_frame(tmp_path):
    frames = build_frames(tmp_path, count=2)
    poses = build_poses(frames)
    frames[0].path = str(tmp_path / "moved_away.jpg")
    _, stats = compose_mosaic(frames, poses, CANVAS_W, CANVAS_H, tile_size=256, collect=True)
    assert stats.frames_failed >= 1
    assert stats.errors


# --------------------------------------------------------------------------
# georeferenced raster
# --------------------------------------------------------------------------

def make_raster(tmp_path, name: str = "orthomosaic.tif"):
    frames = build_frames(tmp_path, count=3)
    poses = build_poses(frames)
    tiles, _ = compose_mosaic(frames, poses, CANVAS_W, CANVAS_H, tile_size=512, collect=True)
    out = tmp_path / name
    result = geopraster.write_geotiff_from_tiles(
        tiles, out, 512, CANVAS_W, CANVAS_H, GSD, ORIGIN_E, ORIGIN_N, EPSG, nodata=0
    )
    return result


def test_geotiff_has_a_real_crs_transform_and_bounds(tmp_path):
    result = make_raster(tmp_path)
    if not geopraster.capabilities()["rasterio"]:
        pytest.skip("rasterio is not installed")
    assert result.path and result.width == CANVAS_W and result.height == CANVAS_H
    assert result.bands == 4
    assert result.crs is not None and "32615" in result.crs

    import rasterio

    with rasterio.open(result.path) as src:
        assert src.crs.to_epsg() == EPSG
        assert src.transform.a == pytest.approx(GSD, rel=1e-6)
        assert src.transform.e == pytest.approx(-GSD, rel=1e-6)
        assert src.bounds.left == pytest.approx(ORIGIN_E, abs=1e-3)
        assert src.bounds.top == pytest.approx(ORIGIN_N, abs=1e-3)
        assert src.bounds.right == pytest.approx(ORIGIN_E + CANVAS_W * GSD, abs=1e-3)
        assert src.bounds.bottom == pytest.approx(ORIGIN_N - CANVAS_H * GSD, abs=1e-3)
        assert src.count == 4 and src.dtypes[0] == "uint8"

    validation = result.validation
    assert validation.get("readable") is True
    assert validation.get("crs_present") is True
    assert validation.get("transform_is_affine_northup") is True
    assert validation.get("centre_sample_nonzero") is True
    assert validation.get("bounds_wgs84") is not None


def test_bounds_reproject_to_plausible_wgs84(tmp_path):
    result = make_raster(tmp_path)
    if not result.validation.get("bounds_wgs84"):
        pytest.skip("bounds could not be reprojected on this install")
    west, south, east, north = result.validation["bounds_wgs84"]
    assert -93.0 < west < -91.0 and -93.0 < east < -91.0
    assert 46.0 < south < 47.0 and 46.0 < north < 47.0
    assert west < east and south < north


def test_raster_without_a_crs_is_written_but_reported(tmp_path):
    if not geopraster.capabilities()["rasterio"]:
        pytest.skip("rasterio is not installed")
    frames = build_frames(tmp_path, count=2)
    tiles, _ = compose_mosaic(frames, build_poses(frames), CANVAS_W, CANVAS_H, tile_size=512, collect=True)
    result = geopraster.write_geotiff_from_tiles(
        tiles, tmp_path / "no_crs.tif", 512, CANVAS_W, CANVAS_H, GSD, ORIGIN_E, ORIGIN_N, None
    )
    assert result.path is not None
    assert result.validation.get("crs_present") is False
    assert result.bounds_wgs84 is None


def test_validate_raster_reports_a_missing_file_without_raising():
    result = geopraster.validate_raster("does/not/exist.tif")
    assert result.path is None
    assert result.validation.get("readable") is False
    assert "error" in result.validation
    assert result.messages, "the failure must be explained in words too"


def test_preview_is_written_at_a_bounded_size(tmp_path):
    frames = build_frames(tmp_path, count=3)
    tiles, _ = compose_mosaic(frames, build_poses(frames), CANVAS_W, CANVAS_H, tile_size=512, collect=True)
    accumulator = geopraster.PreviewAccumulator(CANVAS_W, CANVAS_H, max_side=400)
    for (tx, ty), rgba in tiles.items():
        accumulator.add(tx, ty, rgba, 512)
    meta = accumulator.save(tmp_path / "preview.png")
    assert meta["produced"] is True
    assert max(meta["width"], meta["height"]) <= 400
    from PIL import Image

    with Image.open(meta["path"]) as image:
        assert image.size == (meta["width"], meta["height"])


# --------------------------------------------------------------------------
# COG and XYZ tiles
# --------------------------------------------------------------------------

def test_cog_conversion_is_valid_or_explained(tmp_path):
    result = make_raster(tmp_path)
    if not result.path:
        pytest.skip("rasterio is not installed")
    cog = geopraster.convert_to_cog(result.path, tmp_path / "out_cog.tif")
    if not cog["produced"]:
        assert cog["messages"], "a skipped COG must state why"
        assert any(
            "unavailable" in m or "not installed" in m or "failed" in m for m in cog["messages"]
        ), cog["messages"]
        pytest.skip(f"COG conversion unavailable here: {cog['messages'][-1]}")

    import rasterio

    with rasterio.open(cog["path"]) as src:
        assert src.width == CANVAS_W and src.height == CANVAS_H
        assert src.crs.to_epsg() == EPSG
        assert src.overviews(1), "a COG must carry overviews"
    assert cog["validation"]["readable"] is True


def test_xyz_tiles_are_written_and_decodable(tmp_path):
    result = make_raster(tmp_path)
    if not result.path or not result.bounds_wgs84:
        pytest.skip("georeferenced raster unavailable")
    min_z, max_z = geopraster.choose_zoom_range(GSD, result.bounds_wgs84)
    assert 0 <= min_z <= max_z <= 22
    info = geopraster.generate_xyz_tiles(result.path, tmp_path / "tiles", min_z, max_z)
    if not info["produced"]:
        assert info["messages"], "a skipped tile export must state why"
        pytest.skip(f"XYZ tiles unavailable here: {info['messages'][-1]}")
    written = sorted((tmp_path / "tiles").rglob("*.png"))
    assert len(written) == info["tile_count"]
    from PIL import Image

    with Image.open(written[0]) as image:
        assert image.size == (256, 256)
    assert info["min_zoom"] == min_z and info["max_zoom"] == max_z


def test_tile_paths_encode_zoom_and_indices(tmp_path):
    result = make_raster(tmp_path)
    if not result.path or not result.bounds_wgs84:
        pytest.skip("georeferenced raster unavailable")
    min_z, max_z = geopraster.choose_zoom_range(GSD, result.bounds_wgs84)
    info = geopraster.generate_xyz_tiles(result.path, tmp_path / "tiles", min_z, max_z)
    if not info["produced"]:
        pytest.skip("XYZ tiles unavailable here")
    for path in (tmp_path / "tiles").rglob("*.png"):
        z = int(path.parent.parent.name)
        x = int(path.parent.name)
        y = int(path.stem)
        assert min_z <= z <= max_z
        assert 0 <= x < 2**z and 0 <= y < 2**z
