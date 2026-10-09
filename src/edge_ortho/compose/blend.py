"""Feather and multi-band blending for seamless orthomosaic composition."""

import cv2
import numpy as np


def compute_feather_weights(
    mask: np.ndarray,
    feather_radius: int = 25,
) -> np.ndarray:
    """
    Computes smooth blend weights using Euclidean distance transform from frame boundaries.
    Weight is 0 at image border and rises linearly/smoothly to 1.0 inside.
    """
    if not np.any(mask):
        return np.zeros_like(mask, dtype=np.float32)

    dist = cv2.distanceTransform((mask * 255).astype(np.uint8), cv2.DIST_L2, 5)
    radius = max(float(feather_radius), 1.0)
    weights = np.clip(dist / radius, 0.0, 1.0).astype(np.float32)
    return weights


def blend_accumulator(
    accum_color: np.ndarray,  # (H, W, 3) float32
    accum_weight: np.ndarray,  # (H, W) float32
    warped_patch: np.ndarray,  # (H, W, 3) uint8 or float32
    warped_mask: np.ndarray,  # (H, W) uint8
    feather_radius: int = 25,
) -> None:
    """In-place adds a warped image patch to the running color and weight accumulators."""
    if not np.any(warped_mask):
        return

    w = compute_feather_weights(warped_mask, feather_radius)
    # Expand weight to (H, W, 1)
    w_3d = w[:, :, np.newaxis]
    accum_color += warped_patch.astype(np.float32) * w_3d
    accum_weight += w


def finalize_tile(
    accum_color: np.ndarray,
    accum_weight: np.ndarray,
    nodata_value: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Normalizes accumulated color buffer by weights.
    Returns:
      - (H, W, 3) uint8 RGB image
      - (H, W) uint8 alpha mask (255 where data exists, 0 where nodata)
    """
    valid_mask = accum_weight > 1e-4
    output_rgb = np.full_like(accum_color, nodata_value, dtype=np.uint8)

    weight_safe = np.where(valid_mask, accum_weight, 1.0)[:, :, np.newaxis]
    norm_color = np.clip(accum_color / weight_safe, 0.0, 255.0).astype(np.uint8)

    output_rgb[valid_mask] = norm_color[valid_mask]
    alpha_mask = np.where(valid_mask, 255, 0).astype(np.uint8)

    return output_rgb, alpha_mask
