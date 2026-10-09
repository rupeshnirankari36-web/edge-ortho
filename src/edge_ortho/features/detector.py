"""Downscaled feature extraction (ORB, AKAZE, SIFT) with bounded memory."""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class FrameFeatures:
    frame_id: str
    keypoints_native: np.ndarray  # (N, 2) float32 coordinates in native full-res image pixels
    descriptors: np.ndarray  # (N, D) uint8 or float32 descriptors
    image_shape: tuple[int, int]  # (height, width) of native full-res image
    scale_factor: float  # downscaled / native


def get_feature_detector(
    matcher_name: str = "akaze",
    feature_limit: int = 1500,
) -> cv2.Feature2D:
    """Factory creating configured OpenCV feature detector."""
    name = matcher_name.lower()
    if name == "orb":
        return cv2.ORB_create(
            nfeatures=feature_limit,
            scaleFactor=1.2,
            nlevels=8,
            edgeThreshold=15,
            fastThreshold=20,
        )
    elif name == "akaze":
        return cv2.AKAZE_create(
            descriptor_type=cv2.AKAZE_DESCRIPTOR_MLDB,
            descriptor_size=0,
            descriptor_channels=3,
            threshold=0.001,
            nOctaves=4,
            nOctaveLayers=4,
        )
    elif name == "sift":
        return cv2.SIFT_create(
            nfeatures=feature_limit,
            contrastThreshold=0.04,
            edgeThreshold=10,
            sigma=1.6,
        )
    else:
        # Fallback to AKAZE
        return cv2.AKAZE_create()


def extract_features_from_image(
    image_path: Path,
    frame_id: str,
    detector: cv2.Feature2D,
    max_dim: int = 1000,
) -> FrameFeatures | None:
    """
    Decodes an image once, generates a downscaled grayscale copy (~0.6-1.0 MP),
    extracts keypoints and descriptors, and projects keypoint coordinates back to native resolution.
    """
    try:
        # Read image
        img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if img is None:
            return None

        orig_h, orig_w = img.shape[:2]
        largest_dim = max(orig_h, orig_w)

        if largest_dim > max_dim:
            scale = max_dim / float(largest_dim)
            new_w = int(round(orig_w * scale))
            new_h = int(round(orig_h * scale))
            small_img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        else:
            scale = 1.0
            small_img = img

        gray = cv2.cvtColor(small_img, cv2.COLOR_BGR2GRAY)
        del img  # release native image from memory immediately

        kps, descs = detector.detectAndCompute(gray, None)
        del gray, small_img

        if kps is None or len(kps) == 0 or descs is None:
            return None

        # Convert keypoints to native full-res coordinate space
        pts_downscaled = np.array([kp.pt for kp in kps], dtype=np.float32)
        pts_native = pts_downscaled / scale

        return FrameFeatures(
            frame_id=frame_id,
            keypoints_native=pts_native,
            descriptors=descs,
            image_shape=(orig_h, orig_w),
            scale_factor=scale,
        )
    except Exception:
        return None
