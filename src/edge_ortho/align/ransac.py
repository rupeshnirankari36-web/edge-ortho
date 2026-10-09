"""RANSAC-based geometric transform estimation (Similarity, Affine, Homography)."""

from dataclasses import dataclass
from enum import Enum

import cv2
import numpy as np


class TransformModel(str, Enum):
    SIMILARITY = "similarity"
    AFFINE = "affine"
    HOMOGRAPHY = "homography"


@dataclass
class PairTransform:
    source_id: str
    target_id: str
    model_type: TransformModel
    matrix: np.ndarray  # 3x3 homogeneous matrix mapping source coords -> target coords
    num_matches: int
    num_inliers: int
    inlier_ratio: float
    reprojection_error: float
    status: str  # "success" | "low_inliers" | "failed"


def _compute_reprojection_error(
    src_pts: np.ndarray,
    tgt_pts: np.ndarray,
    H_3x3: np.ndarray,
    inlier_mask: np.ndarray,
) -> float:
    """Computes Root Mean Square (RMS) reprojection error over inliers."""
    idx = np.where(inlier_mask.ravel() == 1)[0]
    if len(idx) == 0:
        return 999.0

    in_src = src_pts[idx]
    in_tgt = tgt_pts[idx]

    # Convert to homogeneous (N, 3)
    ones = np.ones((len(in_src), 1), dtype=np.float32)
    homo_src = np.hstack([in_src, ones])  # (N, 3)

    # Transformed points = homo_src @ H^T
    projected = homo_src @ H_3x3.T
    # Normalize by z coordinate
    z = projected[:, 2:3]
    z[np.abs(z) < 1e-8] = 1e-8
    pred_xy = projected[:, :2] / z

    errors = np.linalg.norm(pred_xy - in_tgt, axis=1)
    rmse = float(np.sqrt(np.mean(errors**2)))
    return rmse


def estimate_pair_transform(
    source_id: str,
    target_id: str,
    src_points: np.ndarray,
    tgt_points: np.ndarray,
    model: TransformModel = TransformModel.AFFINE,
    ransac_thresh_px: float = 4.0,
    min_inliers: int = 15,
) -> PairTransform:
    """
    Estimates 3x3 transformation matrix mapping source coords to target coords
    using RANSAC with the specified geometric model.
    """
    num_matches = len(src_points)
    identity_3x3 = np.eye(3, dtype=np.float64)

    if num_matches < min_inliers:
        return PairTransform(
            source_id=source_id,
            target_id=target_id,
            model_type=model,
            matrix=identity_3x3,
            num_matches=num_matches,
            num_inliers=0,
            inlier_ratio=0.0,
            reprojection_error=999.0,
            status="low_inliers",
        )

    try:
        if model == TransformModel.SIMILARITY:
            M, inliers = cv2.estimateAffinePartial2D(
                src_points,
                tgt_points,
                method=cv2.RANSAC,
                ransacReprojThreshold=ransac_thresh_px,
                maxIters=2000,
                confidence=0.99,
            )
            if M is not None:
                H_3x3 = np.vstack([M, [0.0, 0.0, 1.0]])
            else:
                H_3x3 = None

        elif model == TransformModel.AFFINE:
            M, inliers = cv2.estimateAffine2D(
                src_points,
                tgt_points,
                method=cv2.RANSAC,
                ransacReprojThreshold=ransac_thresh_px,
                maxIters=2000,
                confidence=0.99,
            )
            if M is not None:
                H_3x3 = np.vstack([M, [0.0, 0.0, 1.0]])
            else:
                H_3x3 = None

        elif model == TransformModel.HOMOGRAPHY:
            H_3x3, inliers = cv2.findHomography(
                src_points,
                tgt_points,
                method=cv2.RANSAC,
                ransacReprojThreshold=ransac_thresh_px,
                maxIters=2000,
                confidence=0.99,
            )
        else:
            raise ValueError(f"Unknown transform model: {model}")

        if H_3x3 is None or inliers is None:
            return PairTransform(
                source_id=source_id,
                target_id=target_id,
                model_type=model,
                matrix=identity_3x3,
                num_matches=num_matches,
                num_inliers=0,
                inlier_ratio=0.0,
                reprojection_error=999.0,
                status="failed",
            )

        num_inliers = int(np.sum(inliers))
        inlier_ratio = float(num_inliers) / float(num_matches)

        if num_inliers < min_inliers:
            return PairTransform(
                source_id=source_id,
                target_id=target_id,
                model_type=model,
                matrix=identity_3x3,
                num_matches=num_matches,
                num_inliers=num_inliers,
                inlier_ratio=inlier_ratio,
                reprojection_error=999.0,
                status="low_inliers",
            )

        rmse = _compute_reprojection_error(src_points, tgt_points, H_3x3, inliers)

        # Sanity check determinant to prevent degenerate inversions
        det = np.linalg.det(H_3x3[:2, :2])
        if det <= 0.05 or det >= 20.0 or np.isnan(rmse):
            return PairTransform(
                source_id=source_id,
                target_id=target_id,
                model_type=model,
                matrix=identity_3x3,
                num_matches=num_matches,
                num_inliers=num_inliers,
                inlier_ratio=inlier_ratio,
                reprojection_error=999.0,
                status="failed_degenerate",
            )

        return PairTransform(
            source_id=source_id,
            target_id=target_id,
            model_type=model,
            matrix=H_3x3,
            num_matches=num_matches,
            num_inliers=num_inliers,
            inlier_ratio=inlier_ratio,
            reprojection_error=rmse,
            status="success",
        )
    except Exception:
        return PairTransform(
            source_id=source_id,
            target_id=target_id,
            model_type=model,
            matrix=identity_3x3,
            num_matches=num_matches,
            num_inliers=0,
            inlier_ratio=0.0,
            reprojection_error=999.0,
            status="failed",
        )
