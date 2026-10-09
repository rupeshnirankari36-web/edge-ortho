"""Affine vs. Homography comparison tools and evaluation metrics."""

import time
from dataclasses import dataclass

import numpy as np

from .ransac import PairTransform, TransformModel, estimate_pair_transform


@dataclass
class ModelComparisonResult:
    pair_id: str
    affine: PairTransform
    homography: PairTransform
    affine_time_ms: float
    homography_time_ms: float
    winner: str  # "affine" | "homography" | "tie"
    reason: str


def compare_models_on_pair(
    source_id: str,
    target_id: str,
    src_points: np.ndarray,
    tgt_points: np.ndarray,
    ransac_thresh_px: float = 4.0,
    min_inliers: int = 15,
) -> ModelComparisonResult:
    """Evaluates both Affine and Homography RANSAC fits on the same keypoint matches."""
    t0 = time.perf_counter()
    aff_res = estimate_pair_transform(
        source_id,
        target_id,
        src_points,
        tgt_points,
        model=TransformModel.AFFINE,
        ransac_thresh_px=ransac_thresh_px,
        min_inliers=min_inliers,
    )
    t_aff = (time.perf_counter() - t0) * 1000.0

    t1 = time.perf_counter()
    hom_res = estimate_pair_transform(
        source_id,
        target_id,
        src_points,
        tgt_points,
        model=TransformModel.HOMOGRAPHY,
        ransac_thresh_px=ransac_thresh_px,
        min_inliers=min_inliers,
    )
    t_hom = (time.perf_counter() - t1) * 1000.0

    # Decision logic:
    # If homography failed or was degenerate, affine wins
    if hom_res.status != "success" and aff_res.status == "success":
        winner = "affine"
        reason = f"Homography failed ({hom_res.status})"
    elif aff_res.status != "success" and hom_res.status == "success":
        winner = "homography"
        reason = "Affine failed while homography succeeded"
    elif aff_res.status != "success" and hom_res.status != "success":
        winner = "neither"
        reason = "Both models failed or insufficient inliers"
    else:
        # Both succeeded. If homography reduces reprojection error significantly (>20%) without overfitting:
        err_diff = aff_res.reprojection_error - hom_res.reprojection_error
        if err_diff > 0.5 and hom_res.num_inliers >= aff_res.num_inliers:
            winner = "homography"
            reason = f"Homography reprojection RMSE {hom_res.reprojection_error:.2f}px is lower than affine {aff_res.reprojection_error:.2f}px"
        else:
            # Affine is more constrained and stable for nadir surveys
            winner = "affine"
            reason = f"Affine provides comparable accuracy ({aff_res.reprojection_error:.2f}px vs {hom_res.reprojection_error:.2f}px) with higher stability"

    return ModelComparisonResult(
        pair_id=f"{source_id}<->{target_id}",
        affine=aff_res,
        homography=hom_res,
        affine_time_ms=t_aff,
        homography_time_ms=t_hom,
        winner=winner,
        reason=reason,
    )
