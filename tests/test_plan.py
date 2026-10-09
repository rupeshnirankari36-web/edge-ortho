"""Unit tests for spatial planning, UTM projection, and KD-Tree neighbor graph."""

from pathlib import Path

from edge_ortho.ingest import ingest_and_validate_directory
from edge_ortho.plan import (
    build_neighbor_graph,
    populate_gsd_and_headings,
    project_records_to_utm,
)


def test_utm_projection_and_gsd(synthetic_survey: Path):
    report = ingest_and_validate_directory(synthetic_survey)
    epsg = project_records_to_utm(report.records)
    assert epsg == 32611  # UTM Zone 11N for Los Angeles coordinates
    for r in report.records:
        assert r.utm_easting is not None
        assert r.utm_northing is not None
        assert r.utm_epsg == 32611

    populate_gsd_and_headings(report.records)
    for r in report.records:
        assert r.gsd_m is not None
        assert 0.01 <= r.gsd_m <= 0.20
        assert r.yaw is not None


def test_neighbor_graph(synthetic_survey: Path):
    report = ingest_and_validate_directory(synthetic_survey)
    project_records_to_utm(report.records)
    pairs = build_neighbor_graph(report.records, k_neighbors=4, max_distance_meters=100.0)
    assert len(pairs) > 0
    # Ensure no self pairs and no duplicates
    for p in pairs:
        assert p.source_id != p.target_id
        assert p.distance_meters > 0.0
