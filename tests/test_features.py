"""Unit tests for feature extraction and matching."""

from pathlib import Path

from edge_ortho.features import (
    extract_features_from_image,
    get_feature_detector,
    match_feature_pair,
)


def test_feature_extraction_and_matching(synthetic_survey: Path):
    images = sorted(list(synthetic_survey.glob("*.jpg")))
    detector = get_feature_detector("orb", feature_limit=1000)

    f1 = extract_features_from_image(images[0], images[0].stem, detector, max_dim=800)
    f2 = extract_features_from_image(images[1], images[1].stem, detector, max_dim=800)

    assert f1 is not None
    assert f2 is not None
    assert len(f1.keypoints_native) > 20
    assert len(f2.keypoints_native) > 20

    matched = match_feature_pair(f1, f2, ratio_threshold=0.8)
    assert matched is not None
    assert matched.num_matches >= 8
