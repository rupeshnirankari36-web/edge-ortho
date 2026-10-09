"""Unit tests for ingestion and EXIF parsing."""

from pathlib import Path

from edge_ortho.ingest import extract_frame_metadata, ingest_and_validate_directory


def test_exif_extraction(synthetic_survey: Path):
    images = list(synthetic_survey.glob("*.jpg"))
    assert len(images) > 0
    rec = extract_frame_metadata(images[0])
    assert rec is not None
    assert rec.frame_id == images[0].stem
    assert 34.0 < rec.lat < 35.0
    assert -119.0 < rec.lon < -118.0
    assert rec.altitude == 60.0
    assert rec.width == 640
    assert rec.height == 480
    assert rec.camera_model == "EdgeDrone-2000"


def test_ingest_and_validate(synthetic_survey: Path):
    report = ingest_and_validate_directory(synthetic_survey)
    assert report.total_found == 6
    assert report.accepted_count == 6
    assert report.rejected_count == 0
    assert len(report.records) == 6
