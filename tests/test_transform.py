"""Pair transform estimation and validation.

These tests use constructed correspondences so the expected answer is exactly known:
a transform that is genuinely present must be recovered, and every failure mode the
pipeline depends on (too few inliers, degenerate geometry, excessive residual,
outliers) must be rejected with a status rather than accepted.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from edge_ortho.align.transform import estimate_pair_transform
from edge_ortho.features.matching import FrameFeatures, MatchResult


def features(frame_id: str, n: int, scale: float = 1.0) -> FrameFeatures:
    return FrameFeatures(
        frame_id=frame_id,
        path=f"{frame_id}.jpg",
        scale=scale,
        width=int(4000 * scale),
        height=int(2250 * scale),
        keypoints=[None] * n,
    )


def matches(src_xy: np.ndarray, dst_xy: np.ndarray, status: str = "ok") -> MatchResult:
    return MatchResult(
        status=status,
        raw_matches=len(src_xy),
        ratio_matches=len(src_xy),
        src_points=np.asarray(src_xy, dtype=np.float32).reshape(-1, 1, 2),
        dst_points=np.asarray(dst_xy, dtype=np.float32).reshape(-1, 1, 2),
    )


def rigid(points: np.ndarray, angle_deg: float, tx: float, ty: float, scale: float = 1.0) -> np.ndarray:
    theta = np.radians(angle_deg)
    rot = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    return (points @ (rot * scale).T) + np.array([tx, ty])


@pytest.fixture()
def points() -> np.ndarray:
    rng = np.random.default_rng(12)
    return rng.uniform([0, 0], [2200, 1200], size=(240, 2))


def test_similarity_transform_is_recovered(points):
    dst = rigid(points, angle_deg=4.0, tx=180.0, ty=-60.0, scale=1.01)
    out, geometry = estimate_pair_transform(
        features("a", len(points)), features("b", len(points)), matches(points, dst), model="affine"
    )
    assert out.status == "ok", out.error
    assert out.inliers >= len(points) * 0.95
    assert out.reprojection_error_px is not None and out.reprojection_error_px < 0.5
    assert out.scale == pytest.approx(1.01, abs=0.01)
    assert out.rotation_deg == pytest.approx(4.0, abs=0.4)
    matrix = np.asarray(out.matrix, dtype=np.float64)
    assert matrix[0, 2] == pytest.approx(180.0, abs=1.0)
    assert matrix[1, 2] == pytest.approx(-60.0, abs=1.0)
    assert geometry is not None


def test_geometry_points_are_returned_in_original_frame_pixels(points):
    """The global solver works in full-resolution pixels, so the pairs must be scaled back."""
    scale = 0.25
    dst = rigid(points, 0.0, 40.0, 30.0)
    out, geometry = estimate_pair_transform(
        features("a", len(points), scale=scale),
        features("b", len(points), scale=scale),
        matches(points, dst),
        model="affine",
    )
    assert out.status == "ok"
    assert geometry is not None
    assert geometry.src_points.shape[1] == 2
    assert geometry.src_points.max() == pytest.approx(points.max() / scale, rel=0.05)
    assert geometry.dst_points.max() == pytest.approx((points.max() + 40) / scale, rel=0.05)


def test_transform_with_outliers_rejects_them(points):
    rng = np.random.default_rng(4)
    truth = rigid(points, angle_deg=1.5, tx=25.0, ty=18.0)
    outliers = rng.uniform(0, 1500, size=(60, 2))
    src = np.vstack([points, outliers])
    dst = np.vstack([truth, rng.uniform(0, 1500, size=(60, 2))])
    out, _ = estimate_pair_transform(
        features("a", len(src)), features("b", len(src)), matches(src, dst), model="affine"
    )
    assert out.status == "ok", out.error
    assert out.inliers >= len(points) * 0.9
    assert out.inliers < len(src)
    assert out.inlier_ratio is not None and out.inlier_ratio < 0.95


def test_too_few_inliers_is_rejected(points):
    dst = rigid(points[:6], 0.0, 10.0, 10.0)
    out, geometry = estimate_pair_transform(
        features("a", 6), features("b", 6), matches(points[:6], dst), model="affine", min_inliers=12
    )
    assert out.status != "ok"
    assert geometry is None
    assert "inlier" in (out.error or "")


def test_collinear_points_are_degenerate(points):
    line = np.column_stack([np.linspace(0, 1000, 80), np.full(80, 40.0)])
    dst = rigid(line, 0.0, 5.0, 5.0)
    out, _ = estimate_pair_transform(
        features("a", 80), features("b", 80), matches(line, dst), model="affine"
    )
    assert out.status in {"degenerate_transform", "rejected_by_ransac"}
    assert out.error


def test_high_residual_is_rejected(points):
    """A set with no consistent transform must not pass as an aligned pair."""
    rng = np.random.default_rng(21)
    dst = rng.uniform(0, 2000, size=points.shape)
    out, geometry = estimate_pair_transform(
        features("a", len(points)),
        features("b", len(points)),
        matches(points, dst),
        model="affine",
        max_reprojection_error_px=0.5,
    )
    assert out.status != "ok"
    assert geometry is None
    assert out.status in {"high_reprojection_error", "rejected_by_ransac"}


def test_homography_recovers_a_projective_warp(points):
    src = points
    h_true = np.array([[1.03, 0.02, 35.0], [-0.015, 0.99, 22.0], [1.2e-5, -8e-6, 1.0]])
    hom = np.hstack([src, np.ones((len(src), 1))]) @ h_true.T
    hom /= hom[:, 2:3]
    out, geometry = estimate_pair_transform(
        features("a", len(src)), features("b", len(src)), matches(src, hom[:, :2]), model="homography"
    )
    assert out.status == "ok", out.error
    assert out.reprojection_error_px is not None and out.reprojection_error_px < 0.5
    assert geometry is not None


def test_matching_failure_is_propagated_not_hidden():
    out, geometry = estimate_pair_transform(
        features("a", 0), features("b", 0), MatchResult("insufficient_matches"), model="affine"
    )
    assert out.status == "insufficient_matches"
    assert geometry is None
    assert out.inliers == 0


def test_decode_failure_is_propagated():
    out, _ = estimate_pair_transform(
        features("a", 0), features("b", 0), MatchResult("decode_failed", error="decode_failed"), model="affine"
    )
    assert out.status == "decode_failed"
    assert out.error == "decode_failed"


def test_unsupported_model_raises():
    src = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0], [10.0, 10.0]] * 5)
    with pytest.raises(ValueError):
        estimate_pair_transform(
            features("a", len(src)), features("b", len(src)), matches(src, src), model="polynomial"
        )


def test_identity_transform_has_zero_residual(points):
    out, _ = estimate_pair_transform(
        features("a", len(points)), features("b", len(points)), matches(points, points.copy()), model="affine"
    )
    assert out.status == "ok"
    assert out.reprojection_error_px == pytest.approx(0.0, abs=1e-3)
    assert out.rotation_deg == pytest.approx(0.0, abs=1e-6)
    assert out.scale == pytest.approx(1.0, abs=1e-6)
