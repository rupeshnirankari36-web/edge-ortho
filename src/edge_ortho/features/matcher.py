"""Feature descriptor matching with Lowe's ratio test."""

from dataclasses import dataclass

import cv2
import numpy as np

from .detector import FrameFeatures


@dataclass
class MatchedKeypoints:
    source_id: str
    target_id: str
    src_points: np.ndarray  # (M, 2) in native source image coordinates
    tgt_points: np.ndarray  # (M, 2) in native target image coordinates
    num_matches: int


def match_feature_pair(
    feat1: FrameFeatures,
    feat2: FrameFeatures,
    ratio_threshold: float = 0.75,
) -> MatchedKeypoints | None:
    """Matches descriptors between two frames using BFMatcher and applies Lowe's ratio test."""
    if feat1.descriptors is None or feat2.descriptors is None:
        return None
    if len(feat1.keypoints_native) < 8 or len(feat2.keypoints_native) < 8:
        return None

    # Determine metric by descriptor dtype: uint8 uses HAMMING, float32 uses L2
    if feat1.descriptors.dtype == np.uint8:
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    else:
        matcher = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False)

    try:
        raw_matches = matcher.knnMatch(feat1.descriptors, feat2.descriptors, k=2)
    except Exception:
        return None

    good_src_pts = []
    good_tgt_pts = []

    for match_pair in raw_matches:
        if len(match_pair) == 2:
            m, n = match_pair
            if m.distance < ratio_threshold * n.distance:
                good_src_pts.append(feat1.keypoints_native[m.queryIdx])
                good_tgt_pts.append(feat2.keypoints_native[m.trainIdx])

    if len(good_src_pts) < 6:
        return None

    return MatchedKeypoints(
        source_id=feat1.frame_id,
        target_id=feat2.frame_id,
        src_points=np.array(good_src_pts, dtype=np.float32),
        tgt_points=np.array(good_tgt_pts, dtype=np.float32),
        num_matches=len(good_src_pts),
    )
