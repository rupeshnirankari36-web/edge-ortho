"""Unit tests for geometric alignment and global pose optimization."""

from pathlib import Path

import numpy as np

from edge_ortho.align import TransformModel, estimate_pair_transform, solve_global_poses
from edge_ortho.features import (
    extract_features_from_image,
    get_feature_detector,
    match_feature_pair,
)
from edge_ortho.ingest import ingest_and_validate_directory
from edge_ortho.plan import build_neighbor_graph, populate_gsd_and_headings, project_records_to_utm


def test_pairwise_transform_and_global_solve(synthetic_survey: Path):
    report = ingest_and_validate_directory(synthetic_survey)
    project_records_to_utm(report.records)
    populate_gsd_and_headings(report.records)
    pairs = build_neighbor_graph(report.records, k_neighbors=3, max_distance_meters=80.0)

    detector = get_feature_detector("orb", feature_limit=1000)
    features = {
        r.frame_id: extract_features_from_image(r.path, r.frame_id, detector)
        for r in report.records
    }

    transforms = []
    for p in pairs:
        f1 = features.get(p.source_id)
        f2 = features.get(p.target_id)
        if f1 and f2:
            matched = match_feature_pair(f1, f2, ratio_threshold=0.8)
            if matched:
                pt = estimate_pair_transform(
                    p.source_id,
                    p.target_id,
                    matched.src_points,
                    matched.tgt_points,
                    model=TransformModel.AFFINE,
                )
                transforms.append(pt)

    poses = solve_global_poses(
        records=report.records,
        pair_transforms=transforms,
        target_gsd=report.records[0].gsd_m,
    )

    assert len(poses) == len(report.records)
    for fid, pose in poses.items():
        assert pose.h_native_to_canvas.shape == (3, 3)
        assert not np.isnan(pose.h_native_to_canvas).any()
