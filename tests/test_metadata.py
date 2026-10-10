"""Metadata parsing and frame validation.

Covers the cases the brief calls out: readable GPS-tagged frames, XMP-only altitude
and gimbal heading, missing GPS, unreadable and empty files, and out-of-range or
null-island coordinates. A frame is never accepted on the strength of a partial tag.
"""

from __future__ import annotations

import numpy as np
import pytest

from edge_ortho.ingest.exif import parse_xmp_packet, read_image_metadata
from edge_ortho.ingest.validate import ingest

from conftest import write_geotagged_jpeg, write_plain_jpeg


def test_exif_gps_altitude_and_camera_are_read(tmp_path, scene):
    path = write_geotagged_jpeg(
        tmp_path / "DJI_0001.JPG",
        scene[:384, :512],
        lat=46.842701,
        lon=-91.993802,
        altitude_m=94.5,
        yaw_deg=88.0,
    )
    meta = read_image_metadata(path)
    assert meta.error_code is None
    assert meta.width == 512 and meta.height == 384
    assert meta.latitude == pytest.approx(46.842701, abs=1e-5)
    assert meta.longitude == pytest.approx(-91.993802, abs=1e-5)
    assert meta.altitude_m == pytest.approx(94.5, abs=0.05)
    assert meta.yaw_deg == pytest.approx(88.0, abs=0.1)
    assert meta.make == "DJI"
    assert meta.model == "FC300S"
    assert meta.focal_length_mm == pytest.approx(4.5, abs=0.01)
    assert meta.focal_length_35mm == 26
    assert meta.captured_at is not None


def test_xmp_relative_altitude_and_gimbal_yaw_are_read(tmp_path, scene):
    path = write_geotagged_jpeg(
        tmp_path / "DJI_0002.JPG",
        scene[:384, :512],
        lat=46.842701,
        lon=-91.993802,
        altitude_m=200.0,          # absolute (above sea level)
        xmp_relative_altitude=88.4,  # above ground: what the composer needs
        xmp_gimbal_yaw=-71.25,
        yaw_deg=None,
    )
    meta = read_image_metadata(path)
    assert meta.altitude_m == pytest.approx(88.4, abs=0.05)
    assert meta.altitude_source == "xmp_relative"
    # The tag is normalised into [0, 360); the sign convention (DJI reports the gimbal
    # heading counter-clockwise) is resolved once in the alignment stage, not here.
    assert meta.yaw_deg == pytest.approx(288.75, abs=0.1)
    assert meta.yaw_source == "xmp_gimbal"
    assert meta.pitch_deg == pytest.approx(-90.0, abs=0.01)


def test_xmp_packet_without_namespace_prefixes_is_not_reported_as_truth():
    packet = '<x:xmpmeta xmlns:drone-dji="http://www.dji.com/drone-dji/1.0/"><rdf:RDF><rdf:Description drone-dji:RelativeAltitude="+61.20" drone-dji:GimbalYawDegree="+12.50"/></rdf:RDF></x:xmpmeta>'
    attrs = parse_xmp_packet(packet)
    assert attrs["drone-dji:RelativeAltitude"] == "+61.20"
    assert attrs["drone-dji:GimbalYawDegree"] == "+12.50"


def test_missing_gps_is_rejected_with_a_reason(tmp_path, scene):
    folder = tmp_path / "nogps"
    write_plain_jpeg(folder / "frame_a.jpg", scene[:384, :512])
    write_plain_jpeg(folder / "frame_b.jpg", scene[:384, :520])
    result = ingest(folder)
    assert result.summary["frames_accepted"] == 0
    assert result.summary["frames_rejected"] == 2
    assert result.summary["rejected_by_reason"]["missing_gps"] == 2
    assert result.suitable is False
    assert any("usable GPS" in r for r in result.unsuitability_reasons)
    assert any(w["code"] == "no_geotagged_frames" for w in result.dataset_warnings)
    for frame in result.frames:
        assert frame.accepted is False
        assert frame.reject_reason == "missing_gps"


def test_zero_byte_file_is_rejected_as_unreadable(tmp_path, scene):
    folder = tmp_path / "empty"
    folder.mkdir()
    (folder / "broken.jpg").write_bytes(b"")
    write_geotagged_jpeg(folder / "good.jpg", scene[:384, :512], 46.8, -91.9)
    result = ingest(folder)
    broken = next(f for f in result.frames if f.filename == "broken.jpg")
    assert broken.accepted is False
    assert broken.reject_reason == "zero_size"
    assert result.summary["frames_accepted"] == 1


def test_garbage_bytes_are_reported_not_crashed(tmp_path):
    folder = tmp_path / "corrupt"
    folder.mkdir()
    (folder / "junk.jpg").write_bytes(b"this is not a jpeg" * 40)
    result = ingest(folder)
    frame = result.frames[0]
    assert frame.accepted is False
    assert frame.reject_reason in {"decode_failed", "unreadable"}


def test_truncated_jpeg_does_not_raise(tmp_path, scene):
    path = write_geotagged_jpeg(tmp_path / "truncated.jpg", scene[:384, :512], 46.8, -91.9)
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 3])
    meta = read_image_metadata(path)
    # Either it still reports dimensions or it reports why not - never an exception.
    assert meta.width is None or meta.width > 0
    if meta.width is None:
        assert meta.error_code is not None


def test_recognised_but_unsupported_formats_are_reported(tmp_path, scene):
    """Imagery outside the ingestion contract is listed, not silently dropped."""
    folder = tmp_path / "mixed"
    folder.mkdir()
    write_geotagged_jpeg(folder / "DJI_0001.JPG", scene[:384, :512], 46.8, -91.9)
    (folder / "preview.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (folder / "DJI_0002.DNG").write_bytes(b"raw")
    # A note is not imagery, so it must not be counted as a skipped image.
    (folder / "notes.txt").write_text("flight notes", encoding="utf-8")
    result = ingest(folder)
    assert len(result.discovery.images) == 1
    assert sorted(result.discovery.skipped_unsupported) == ["DJI_0002.DNG", "preview.png"]
    assert result.summary["unsupported_files_skipped"] == 2


def test_null_island_coordinates_are_invalid(tmp_path, scene):
    folder = tmp_path / "null"
    path = folder / "zero.jpg"
    folder.mkdir()
    write_geotagged_jpeg(path, scene[:384, :512], lat=0.0, lon=0.0)
    result = ingest(folder)
    assert result.frames[0].reject_reason == "invalid_gps"
    assert result.summary["frames_accepted"] == 0


def test_gsd_is_derived_from_altitude_and_focal_length(tmp_path, scene):
    folder = tmp_path / "gsd"
    folder.mkdir()
    for i in range(3):
        write_geotagged_jpeg(
            folder / f"f{i}.jpg",
            scene[:384, :512],
            lat=46.84 + i * 1e-5,
            lon=-91.99 + i * 1e-5,
            altitude_m=100.0,
            focal_length_mm=4.5,
            focal_length_35mm=26,
        )
    result = ingest(folder)
    frame = result.frames[0]
    assert frame.gsd_m is not None and frame.gsd_m > 0
    assert frame.gsd_source in {"35mm_equiv", "exif_focal", "sensor_width"}
    assert frame.footprint_w_m == pytest.approx(512 * frame.gsd_m, rel=1e-6)
    assert result.summary["gsd_available"] is True


def test_altitude_without_relative_reading_is_flagged_not_silently_used(tmp_path, scene):
    """Absolute altitude is kept but marked, so the composer can refuse to trust it."""
    path = write_geotagged_jpeg(
        tmp_path / "abs.jpg", scene[:384, :512], 46.8, -91.9, altitude_m=312.0, xmp_relative_altitude=None
    )
    meta = read_image_metadata(path)
    assert meta.altitude_m == pytest.approx(312.0, abs=0.1)
    assert meta.altitude_source in {"exif_gps", "xmp_absolute"}
    assert "absolute_altitude_only" in meta.warnings

    # ...and the dataset report has to say so too, rather than only the frame record.
    folder = tmp_path / "absolute"
    folder.mkdir()
    for i in range(4):
        write_geotagged_jpeg(
            folder / f"f{i}.jpg",
            scene[:384, :512],
            lat=46.84 + i * 1e-5,
            lon=-91.99 + i * 1e-5,
            altitude_m=312.0,
        )
    result = ingest(folder)
    codes = {w["code"] for w in result.dataset_warnings}
    assert "absolute_altitude_only" in codes
    assert any("above-ground" in r for r in result.unsuitability_reasons)
