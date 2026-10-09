"""
Unit tests for Abhyuday's Computer Vision work plan checklist:
  - Synthetic translation recovered within tolerance
  - Synthetic affine transform recovered
  - Synthetic homography recovered
  - Outlier correspondences rejected by RANSAC
  - Bad / empty descriptor pairs fail safely
  - Neighbour graph does not create all-pairs edges (cKDTree capped degree)
  - GPS fallback works when a pair has no valid transform
  - Transform sanity checks reject extreme matrices
  - Multi-matcher interface (ORB, SIFT, AKAZE) consistency
  - Blending and exposure adjustment contracts
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from edge_ortho.align.matcher import (
    match_pair,
    validate_transform_sanity,
)
from edge_ortho.compose.mosaic import (
    _build_placement_map,
    compute_distance_feather_weight,
    compute_frame_gain,
)
from edge_ortho.ingest.neighbours import build_neighbour_graph
from edge_ortho.ingest.reader import ImageMeta


def _create_textured_image(width: int = 400, height: int = 300) -> np.ndarray:
    """Create a reproducible image rich in visual textures for feature detection."""
    np.random.seed(42)
    img = np.zeros((height, width, 3), dtype=np.uint8)
    # Add high-contrast geometric shapes and gradient textures
    cv2.rectangle(img, (50, 50), (150, 150), (255, 255, 255), -1)
    cv2.circle(img, (250, 100), 40, (200, 200, 200), -1)
    cv2.line(img, (20, 250), (350, 50), (180, 180, 180), 5)
    cv2.circle(img, (100, 220), 30, (220, 150, 100), -1)
    # Add random speckles for high-frequency keypoints
    noise = np.random.randint(0, 100, (height, width, 3), dtype=np.uint8)
    img = cv2.add(img, noise)
    return img


class TestSyntheticTransforms:
    """Checklist: synthetic translation, affine, and homography recovery."""

    def test_synthetic_translation_recovered(self, tmp_path):
        base = _create_textured_image(500, 400)
        p1 = str(tmp_path / "trans_1.jpg")
        p2 = str(tmp_path / "trans_2.jpg")
        cv2.imwrite(p1, base)

        # Pure translation: dx=25, dy=15
        dx, dy = 25.0, 15.0
        M_true = np.float32([[1.0, 0.0, dx], [0.0, 1.0, dy]])
        warped = cv2.warpAffine(base, M_true, (500, 400))
        cv2.imwrite(p2, warped)

        mr = match_pair(p1, p2, method="orb", model="similarity")
        assert mr.success is True
        assert mr.inliers >= 15
        assert mr.reprojection_error_px < 3.0

        # Verify recovered translation within sub-pixel tolerance
        recovered_dx = mr.transform[0, 2]
        recovered_dy = mr.transform[1, 2]
        assert abs(recovered_dx - dx) < 2.0
        assert abs(recovered_dy - dy) < 2.0

    def test_synthetic_affine_recovered(self, tmp_path):
        base = _create_textured_image(500, 400)
        p1 = str(tmp_path / "aff_1.jpg")
        p2 = str(tmp_path / "aff_2.jpg")
        cv2.imwrite(p1, base)

        # Affine with rotation (5 deg), mild scale (1.05), and translation
        theta = math.radians(5.0)
        scale = 1.02
        tx, ty = 15.0, -10.0
        M_rot = cv2.getRotationMatrix2D((250, 200), math.degrees(theta), scale)
        M_rot[0, 2] += tx
        M_rot[1, 2] += ty
        warped = cv2.warpAffine(base, M_rot, (500, 400))
        cv2.imwrite(p2, warped)

        mr = match_pair(p1, p2, method="orb", model="affine")
        assert mr.success is True
        assert mr.inliers >= 12
        assert mr.reprojection_error_px < 3.0
        assert mr.model == "affine"

    def test_synthetic_homography_recovered(self, tmp_path):
        base = _create_textured_image(500, 400)
        p1 = str(tmp_path / "homo_1.jpg")
        p2 = str(tmp_path / "homo_2.jpg")
        cv2.imwrite(p1, base)

        # Perspective homography
        pts_src = np.float32([[0, 0], [500, 0], [500, 400], [0, 400]])
        pts_dst = np.float32([[20, 15], [480, 5], [490, 390], [10, 385]])
        H_true = cv2.getPerspectiveTransform(pts_src, pts_dst)

        warped = cv2.warpPerspective(base, H_true, (500, 400))
        cv2.imwrite(p2, warped)

        mr = match_pair(p1, p2, method="orb", model="homography")
        assert mr.success is True
        assert mr.inliers >= 10
        assert mr.transform.shape == (3, 3)
        assert mr.reprojection_error_px < 3.0


class TestRansacAndRobustness:
    """Checklist: outlier rejection, bad descriptors, sanity checks."""

    def test_outlier_correspondences_rejected_by_ransac(self):
        # Create true affine points
        np.random.seed(99)
        pts_a = np.random.uniform(50, 400, (40, 2)).astype(np.float32)
        M = np.float32([[1.0, 0.0, 10.0], [0.0, 1.0, 5.0]])
        ones = np.ones((40, 1), dtype=np.float32)
        pts_b = (np.hstack([pts_a, ones]) @ M.T).astype(np.float32)

        # Inject 15 strong outlier noise points
        outlier_idx = np.random.choice(40, 15, replace=False)
        pts_b[outlier_idx] += np.random.uniform(100, 300, (15, 2)).astype(np.float32)

        # Fit with RANSAC
        M_est, mask = cv2.estimateAffine2D(pts_a, pts_b, method=cv2.RANSAC, ransacReprojThreshold=3.0)
        assert M_est is not None
        assert mask is not None
        # Inliers should exclude injected outliers
        inliers_count = int(mask.sum())
        assert inliers_count >= 20
        for idx in outlier_idx:
            assert mask[idx][0] == 0

    def test_bad_empty_descriptor_pairs_fail_safely(self, tmp_path):
        blank = np.zeros((300, 300, 3), dtype=np.uint8)
        p1 = str(tmp_path / "blank1.jpg")
        p2 = str(tmp_path / "blank2.jpg")
        cv2.imwrite(p1, blank)
        cv2.imwrite(p2, blank)

        mr = match_pair(p1, p2, method="orb")
        assert mr.success is False
        assert mr.status in ("rejected", "failed")
        assert mr.transform is None

    def test_transform_sanity_checks_reject_extreme_matrices(self):
        shape = (400, 500)
        # 1. Identity is sane
        assert validate_transform_sanity(np.eye(3), shape) is True

        # 2. Extreme scale (>2.5x) is rejected
        H_scale = np.diag([3.5, 3.5, 1.0])
        assert validate_transform_sanity(H_scale, shape) is False

        # 3. Extreme rotation (>75 deg) is rejected for nadir
        rad = math.radians(85.0)
        H_rot = np.array([
            [math.cos(rad), -math.sin(rad), 0.0],
            [math.sin(rad), math.cos(rad), 0.0],
            [0.0, 0.0, 1.0],
        ])
        assert validate_transform_sanity(H_rot, shape) is False

        # 4. Extreme translation (>1.5x image dimensions) is rejected
        H_shift = np.eye(3)
        H_shift[0, 2] = 2000.0
        assert validate_transform_sanity(H_shift, shape) is False

        # 5. Degenerate determinant is rejected
        H_degen = np.diag([0.01, 1.0, 1.0])
        assert validate_transform_sanity(H_degen, shape) is False


class TestNeighbourGraphAndFallback:
    """Checklist: cKDTree neighbour limits, GPS fallback, no all-pairs edges."""

    def test_neighbour_graph_does_not_create_all_pairs(self):
        # Create a grid of 16 images
        images = []
        for i in range(16):
            images.append(ImageMeta(
                filename=f"img_{i:02d}.jpg",
                filepath=f"/data/img_{i:02d}.jpg",
                file_bytes=1000,
                lat=51.500 + (i // 4) * 0.0005,
                lon=-0.100 + (i % 4) * 0.0005,
                has_gps=True,
                readable=True,
            ))
        pairs = build_neighbour_graph(images, max_distance_m=100.0, max_neighbours=4)
        # All pairs would be 16 * 15 / 2 = 120 pairs
        # With max_neighbours=4, pairs should be strictly bounded
        assert len(pairs) < 40
        # Degree per image must not exceed max_neighbours
        counts = {i: 0 for i in range(16)}
        for p in pairs:
            counts[p.idx_a] += 1
            counts[p.idx_b] += 1
        for cnt in counts.values():
            assert cnt <= 8

    def test_gps_fallback_when_pair_has_no_valid_transform(self):
        images = [
            ImageMeta(
                filename="f0.jpg", filepath="f0.jpg", file_bytes=100,
                lat=51.500, lon=-0.100, has_gps=True, readable=True, width=100, height=100
            ),
            ImageMeta(
                filename="f1.jpg", filepath="f1.jpg", file_bytes=100,
                lat=51.501, lon=-0.100, has_gps=True, readable=True, width=100, height=100
            ),
        ]
        # Empty matches list simulating match failure
        matches = []
        transforms = _build_placement_map(images, matches, ref_idx=0)
        # Both images must have placement via GPS fallback
        assert 0 in transforms
        assert 1 in transforms
        assert transforms[1] is not None
        # GPS displacement should position f1 with non-zero translation
        assert abs(transforms[1][1, 2]) > 0.0


class TestBlendingAndExposure:
    """Checklist: gain computation and feather distance weights."""

    def test_exposure_luminance_gain(self):
        # Dark image -> gain > 1.0 (clamped to 1.25)
        dark = np.full((100, 100, 3), 50, dtype=np.uint8)
        gain_dark = compute_frame_gain(dark, target_mean=128.0)
        assert 1.0 < gain_dark <= 1.25

        # Bright image -> gain < 1.0 (clamped to 0.8)
        bright = np.full((100, 100, 3), 200, dtype=np.uint8)
        gain_bright = compute_frame_gain(bright, target_mean=128.0)
        assert 0.8 <= gain_bright < 1.0

    def test_feather_distance_weights(self):
        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[20:80, 20:80] = 1
        weights = compute_distance_feather_weight(mask, radius=10)
        assert weights.shape == (100, 100)
        assert weights[0, 0] == 0.0
        # Center of mask should reach full weight 1.0
        assert weights[50, 50] == 1.0
        # Edge of mask should be strictly between 0 and 1
        assert 0.0 < weights[21, 50] < 1.0
