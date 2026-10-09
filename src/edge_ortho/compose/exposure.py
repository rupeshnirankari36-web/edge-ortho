"""Exposure and luminance compensation across overlapping aerial frames."""

import cv2
import numpy as np


def compute_frame_luminance_gain(
    image: np.ndarray,
    target_mean: float = 128.0,
) -> float:
    """Computes a gentle gain multiplier to balance overall frame brightness without blowing out highlights."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mean_val = float(np.mean(gray))
    if mean_val < 10.0 or mean_val > 245.0:
        return 1.0  # Avoid extreme scaling on black/white frames

    raw_gain = target_mean / mean_val
    # Clamp gain between 0.8 and 1.25 to prevent harsh exposure artifacts
    clamped_gain = max(0.8, min(1.25, raw_gain))
    return float(clamped_gain)


def apply_gain(image: np.ndarray, gain: float) -> np.ndarray:
    """Applies gain scaling to a BGR image with saturation clipping."""
    if abs(gain - 1.0) < 0.01:
        return image
    return np.clip(image.astype(np.float32) * gain, 0.0, 255.0).astype(np.uint8)
