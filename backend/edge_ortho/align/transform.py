"""Stage 6a - robustly fit and validate a transform for one image pair.

Both model families from the brief are supported and validated the same way:

* ``similarity`` / ``affine`` via ``cv2.estimateAffinePartial2D`` /
  ``cv2.estimateAffine2D`` with RANSAC;
* ``homography`` via ``cv2.findHomography`` with RANSAC.

A fit is only accepted when it passes *every* check below, and the failing check
is recorded as the pair status. This is what keeps a bad pair out of the global
solution instead of letting it drag the whole mosaic:

* enough inliers after RANSAC;
* inlier ratio above a floor (a fit that explains 4 of 400 matches is luck);
* reprojection RMSE under the configured threshold;
* non-degenerate similarity: finite, positive scale within a sane band, and a
  positive determinant (no reflection).

Reprojection error is reported in matching-copy pixels and, when a GSD estimate
exists, converted to metres so the number means something on the ground.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import cv2
import numpy as np

from ..contracts import PairTransform
from ..features.matching import FrameFeatures, MatchResult

MIN_INLIER_RATIO = 0.25
SCALE_BAND = (0.25, 4.0)


@dataclass
class PairGeometry:
    """Inlier correspondences in *original* image pixel coordinates.

    Kept out of the persisted contract: it can be large, and it is only needed
    by the global solver within a single run.
    """

    source_id: str
    target_id: str
    src_points: np.ndarray  # (N, 2) original pixels of source frame
    dst_points: np.ndarray  # (N, 2) original pixels of target frame


def _matrix3x3(m: np.ndarray | None, model: str) -> list[list[float]] | None:
    if m is None:
        return None
    m = np.asarray(m, dtype=np.float64)
    if model == "homography":
        if m.shape != (3, 3):
            return None
        mat = m
    else:
        if m.shape != (2, 3):
            return None
        mat = np.vstack([m, [0.0, 0.0, 1.0]])
    if not np.all(np.isfinite(mat)):
        return None
    return [[float(v) for v in row] for row in mat]


def _reprojection_error(m: np.ndarray, src_pts: np.ndarray, dst_pts: np.ndarray, model: str):
    src = src_pts.astype(np.float64).reshape(-1, 1, 2)
    if model == "homography":
        proj = cv2.perspectiveTransform(src, m)
    else:
        # cv2.transform needs an n x (n+1) matrix for 2-channel points.
        proj = cv2.transform(src, np.asarray(m, dtype=np.float64)[:2, :])
    diff = proj.reshape(-1, 2) - dst_pts.reshape(-1, 2)
    errors = np.linalg.norm(diff, axis=1)
    return float(np.sqrt(np.mean(errors**2))), errors


def _similarity_terms(m3: np.ndarray) -> tuple[float, float]:
    """Scale and rotation (degrees) of a similarity/affine matrix."""
    a, b = m3[0, 0], m3[0, 1]
    c, d = m3[1, 0], m3[1, 1]
    # Average the two column norms so mild anisotropy in a full affine fit is
    # reported as one effective scale rather than silently ignored.
    scale = 0.5 * (math.hypot(a, b) + math.hypot(c, d))
    rotation = math.degrees(math.atan2(c, a))
    return scale, rotation


def _degenerate_reason(m3: np.ndarray, model: str, scale: float) -> str | None:
    if not np.all(np.isfinite(m3)):
        return "non-finite coefficients"
    det = m3[0, 0] * m3[1, 1] - m3[0, 1] * m3[1, 0]
    if det <= 0:
        return f"negative determinant ({det:.4g}): mirrored or collapsed transform"
    if model != "homography" and not (SCALE_BAND[0] <= scale <= SCALE_BAND[1]):
        return f"implausible scale {scale:.3g} outside {SCALE_BAND}"
    return None


def estimate_pair_transform(
    src: FrameFeatures,
    dst: FrameFeatures,
    matches: MatchResult,
    model: str = "affine",
    ransac_threshold_px: float = 3.0,
    ransac_confidence: float = 0.999,
    ransac_max_iters: int = 5000,
    min_inliers: int = 12,
    max_reprojection_error_px: float = 3.0,
    gsd_m: float | None = None,
    max_constraint_points: int = 24,
) -> tuple[PairTransform, PairGeometry | None]:
    """Fit one pair and return its record plus the inlier geometry for the solver."""
    out = PairTransform(
        source_id=src.frame_id,
        target_id=dst.frame_id,
        model=model,
        status="insufficient_matches",
        keypoints_source=src.count,
        keypoints_target=dst.count,
    )

    if matches.status != "ok" or matches.src_points is None:
        out.status = matches.status
        out.raw_matches = matches.raw_matches
        out.ratio_filtered_matches = matches.ratio_matches
        out.error = matches.error
        return out, None

    out.raw_matches = matches.raw_matches
    out.ratio_filtered_matches = matches.ratio_matches
    src_pts = matches.src_points.astype(np.float64).reshape(-1, 1, 2)
    dst_pts = matches.dst_points.astype(np.float64).reshape(-1, 1, 2)

    t0 = time.perf_counter()
    try:
        if model == "homography":
            m, mask = cv2.findHomography(
                src_pts,
                dst_pts,
                method=cv2.RANSAC,
                ransacReprojThreshold=ransac_threshold_px,
                maxIters=int(ransac_max_iters),
                confidence=float(ransac_confidence),
            )
        elif model == "similarity":
            m, mask = cv2.estimateAffinePartial2D(
                src_pts,
                dst_pts,
                method=cv2.RANSAC,
                ransacReprojThreshold=ransac_threshold_px,
                maxIters=int(ransac_max_iters),
                confidence=float(ransac_confidence),
            )
        elif model == "affine":
            m, mask = cv2.estimateAffine2D(
                src_pts,
                dst_pts,
                method=cv2.RANSAC,
                ransacReprojThreshold=ransac_threshold_px,
                maxIters=int(ransac_max_iters),
                confidence=float(ransac_confidence),
            )
        else:
            raise ValueError(f"unsupported pair model {model!r}")
    except cv2.error as exc:
        out.status = "degenerate_transform"
        out.error = f"opencv_error: {exc}"
        out.match_ms = (time.perf_counter() - t0) * 1000.0
        return out, None

    out.match_ms = (time.perf_counter() - t0) * 1000.0

    if m is None or mask is None:
        out.status = "rejected_by_ransac"
        out.error = "RANSAC found no consistent model"
        return out, None

    inlier_mask = mask.ravel().astype(bool)
    inliers = int(inlier_mask.sum())
    out.inliers = inliers
    out.inlier_ratio = inliers / float(len(inlier_mask)) if len(inlier_mask) else None

    if inliers < min_inliers:
        out.status = "rejected_by_ransac"
        out.error = f"{inliers} inliers below minimum {min_inliers}"
        return out, None
    if out.inlier_ratio is not None and out.inlier_ratio < MIN_INLIER_RATIO:
        out.status = "rejected_by_ransac"
        out.error = (
            f"inlier ratio {out.inlier_ratio:.2f} below floor {MIN_INLIER_RATIO:g} "
            "for a ratio-filtered match set"
        )
        return out, None

    matrix = _matrix3x3(m, model)
    if matrix is None:
        out.status = "degenerate_transform"
        out.error = "transform is not finite"
        return out, None
    m3 = np.asarray(matrix, dtype=np.float64)

    scale, rotation = _similarity_terms(m3)
    reason = _degenerate_reason(m3, model, scale)
    if reason:
        out.status = "degenerate_transform"
        out.error = reason
        return out, None

    rmse, errors = _reprojection_error(m3, src_pts, dst_pts, model)
    rmse_inliers = float(np.sqrt(np.mean(errors[inlier_mask] ** 2))) if inliers else rmse
    out.reprojection_error_px = rmse_inliers
    if gsd_m:
        out.reprojection_error_m = rmse_inliers * gsd_m

    if rmse_inliers > max_reprojection_error_px:
        out.status = "high_reprojection_error"
        out.error = (
            f"inlier RMSE {rmse_inliers:.2f} px exceeds {max_reprojection_error_px:.2f} px"
        )
        out.matrix = matrix
        out.scale, out.rotation_deg = scale, rotation
        return out, None

    out.status = "ok"
    out.matrix = matrix
    out.scale, out.rotation_deg = scale, rotation

    # --- correspondences in original-image pixels for the global solver ----
    inlier_idx = np.flatnonzero(inlier_mask)
    if len(inlier_idx) > max_constraint_points:
        step = max(1, len(inlier_idx) // max_constraint_points)
        inlier_idx = inlier_idx[::step][:max_constraint_points]
    src_orig = src_pts.reshape(-1, 2)[inlier_idx] / max(src.scale, 1e-9)
    dst_orig = dst_pts.reshape(-1, 2)[inlier_idx] / max(dst.scale, 1e-9)
    geometry = PairGeometry(src.frame_id, dst.frame_id, src_orig, dst_orig)
    return out, geometry
