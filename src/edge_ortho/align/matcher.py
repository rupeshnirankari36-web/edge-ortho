from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Optional, Tuple, Any

import cv2
import numpy as np


DEFAULT_MATCH_PIXELS = 600_000   # ~0.6 MP working resolution
ORB_N_FEATURES = 2000
AKAZE_N_FEATURES = 1500
SIFT_N_FEATURES = 1500
LOWE_RATIO = 0.75
RANSAC_THRESHOLD = 3.0
MIN_INLIERS = 8


@dataclass
class MatchResult:
    filename_a: str
    filename_b: str
    source_id: str = ""
    target_id: str = ""
    model: str = "affine"
    keypoints_a: int = 0
    keypoints_b: int = 0
    raw_matches: int = 0
    candidate_matches: int = 0
    ratio_passed: int = 0
    inliers: int = 0
    inlier_ratio: float = 0.0
    reprojection_error_px: float = 0.0
    status: str = "rejected"
    success: bool = False
    transform: Optional[np.ndarray] = field(default=None, repr=False)
    matrix: Optional[list] = None
    error: Optional[str] = None
    scale_factor: float = 1.0  # downscale ratio applied

    def __post_init__(self):
        if not self.source_id and self.filename_a:
            self.source_id = os.path.splitext(self.filename_a)[0]
        if not self.target_id and self.filename_b:
            self.target_id = os.path.splitext(self.filename_b)[0]
        if self.candidate_matches == 0:
            self.candidate_matches = self.ratio_passed

    def to_pair_record(self) -> dict[str, Any]:
        """Convert to the standard pair transform JSON contract for Rupesh/Naman."""
        mat_list = []
        if self.transform is not None:
            if self.transform.shape == (2, 3):
                mat_list = [
                    [float(self.transform[0, 0]), float(self.transform[0, 1]), float(self.transform[0, 2])],
                    [float(self.transform[1, 0]), float(self.transform[1, 1]), float(self.transform[1, 2])],
                    [0.0, 0.0, 1.0],
                ]
            elif self.transform.shape == (3, 3):
                mat_list = self.transform.astype(float).tolist()

        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "model": self.model,
            "matrix": mat_list if mat_list else [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "matches": self.candidate_matches,
            "candidate_matches": self.candidate_matches,
            "inliers": self.inliers,
            "inlier_ratio": round(float(self.inlier_ratio), 4),
            "reprojection_error": round(float(self.reprojection_error_px), 3),
            "reprojection_error_px": round(float(self.reprojection_error_px), 3),
            "status": self.status,
        }


def _downscale_image(img: np.ndarray, target_pixels: int) -> tuple[np.ndarray, float]:
    """Return (resized_image, scale_factor) where scale_factor <= 1."""
    h, w = img.shape[:2]
    pixels = h * w
    if pixels <= target_pixels:
        return img, 1.0
    scale = math.sqrt(target_pixels / float(pixels))
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return resized, scale


def get_detector_and_norm(method: str = "orb") -> tuple[cv2.Feature2D, int]:
    """Factory returning OpenCV feature detector and corresponding distance norm."""
    m = method.lower().strip()
    if m == "sift":
        return cv2.SIFT_create(nfeatures=SIFT_N_FEATURES), cv2.NORM_L2
    elif m == "akaze":
        if hasattr(cv2, "AKAZE_create"):
            return cv2.AKAZE_create(), cv2.NORM_HAMMING
        elif hasattr(cv2, "xfeatures2d_AKAZE"):
            return cv2.xfeatures2d_AKAZE.create(), cv2.NORM_HAMMING
        else:
            return cv2.ORB_create(nfeatures=ORB_N_FEATURES), cv2.NORM_HAMMING
    else:
        # Default ORB baseline
        return cv2.ORB_create(nfeatures=ORB_N_FEATURES), cv2.NORM_HAMMING


def compute_reprojection_error(
    pts_a: np.ndarray,
    pts_b: np.ndarray,
    H_3x3: np.ndarray,
    inliers_mask: np.ndarray,
) -> float:
    """Compute RMSE reprojection error in pixels across inlier points."""
    idx = np.where(inliers_mask.ravel() == 1)[0]
    if len(idx) == 0:
        return 999.0

    in_a = pts_a[idx]
    in_b = pts_b[idx]

    ones = np.ones((len(in_a), 1), dtype=np.float32)
    homo_a = np.hstack([in_a, ones])
    projected = homo_a @ H_3x3.T
    z = projected[:, 2:3]
    z[np.abs(z) < 1e-8] = 1e-8
    pred_b = projected[:, :2] / z

    errors = np.linalg.norm(pred_b - in_b, axis=1)
    return float(np.sqrt(np.mean(errors ** 2)))


def validate_transform_sanity(
    H_3x3: np.ndarray,
    img_shape: tuple[int, int],
    max_scale_factor: float = 2.5,
    max_rotation_deg: float = 75.0,
    max_shift_ratio: float = 1.5,
) -> bool:
    """
    Sanity check to reject impossible scale, extreme rotation, or unreasonable displacement.
    """
    try:
        det = float(np.linalg.det(H_3x3[:2, :2]))
        if det <= 0.05 or det >= 20.0 or math.isnan(det):
            return False

        # Scale checks
        sx = math.sqrt(H_3x3[0, 0] ** 2 + H_3x3[1, 0] ** 2)
        sy = math.sqrt(H_3x3[0, 1] ** 2 + H_3x3[1, 1] ** 2)
        if sx < (1.0 / max_scale_factor) or sx > max_scale_factor:
            return False
        if sy < (1.0 / max_scale_factor) or sy > max_scale_factor:
            return False

        # Rotation check (for mostly nadir flight lines)
        rot_rad = math.atan2(H_3x3[1, 0], H_3x3[0, 0])
        rot_deg = abs(math.degrees(rot_rad))
        if rot_deg > 180.0:
            rot_deg = 360.0 - rot_deg
        if rot_deg > max_rotation_deg:
            return False

        # Shift / translation sanity
        h, w = img_shape
        tx, ty = abs(H_3x3[0, 2]), abs(H_3x3[1, 2])
        if tx > w * max_shift_ratio or ty > h * max_shift_ratio:
            return False

        return True
    except Exception:
        return False


def match_pair(
    path_a: str,
    path_b: str,
    target_pixels: int = DEFAULT_MATCH_PIXELS,
    method: str = "orb",
    model: str = "affine",
    save_debug_path: Optional[str] = None,
) -> MatchResult:
    """
    Match a single image pair with chosen detector (orb, akaze, sift) and alignment model (affine, homography, similarity).
    
    1. Downscales both images safely to ~0.6 MP (configurable).
    2. Detects keypoints and descriptors.
    3. Matches with BFMatcher + Lowe's ratio test.
    4. Filters outliers with RANSAC using the specified geometric model.
    5. Validates transform sanity (rejects extreme rotation, scaling, displacement).
    6. Returns structured MatchResult with candidate matches, inliers, ratio, error, and status.
    7. Optionally generates a visual match/debug output image.
    """
    fname_a = os.path.basename(path_a)
    fname_b = os.path.basename(path_b)
    result = MatchResult(
        filename_a=fname_a,
        filename_b=fname_b,
        source_id=os.path.splitext(fname_a)[0],
        target_id=os.path.splitext(fname_b)[0],
        model=model.lower(),
    )

    img_a_full = cv2.imread(path_a, cv2.IMREAD_GRAYSCALE)
    img_b_full = cv2.imread(path_b, cv2.IMREAD_GRAYSCALE)

    if img_a_full is None:
        result.error = f"Cannot read {path_a}"
        result.status = "failed"
        return result
    if img_b_full is None:
        result.error = f"Cannot read {path_b}"
        result.status = "failed"
        return result

    img_a, scale_a = _downscale_image(img_a_full, target_pixels)
    img_b, scale_b = _downscale_image(img_b_full, target_pixels)
    del img_a_full, img_b_full
    result.scale_factor = (scale_a + scale_b) / 2.0

    detector, norm_type = get_detector_and_norm(method)
    kp_a, des_a = detector.detectAndCompute(img_a, None)
    kp_b, des_b = detector.detectAndCompute(img_b, None)

    result.keypoints_a = len(kp_a) if kp_a else 0
    result.keypoints_b = len(kp_b) if kp_b else 0

    if des_a is None or des_b is None or len(kp_a) < 4 or len(kp_b) < 4:
        result.error = "Insufficient keypoints"
        result.status = "rejected"
        return result

    bf = cv2.BFMatcher(norm_type, crossCheck=False)
    raw = bf.knnMatch(des_a, des_b, k=2)
    result.raw_matches = len(raw)

    good: list[cv2.DMatch] = []
    for m_pair in raw:
        if len(m_pair) == 2:
            m, n = m_pair
            if m.distance < LOWE_RATIO * n.distance:
                good.append(m)

    result.ratio_passed = len(good)
    result.candidate_matches = len(good)

    if len(good) < MIN_INLIERS:
        result.error = f"Too few ratio-filtered matches: {len(good)}"
        result.status = "rejected"
        return result

    pts_a = np.float32([kp_a[m.queryIdx].pt for m in good])
    pts_b = np.float32([kp_b[m.trainIdx].pt for m in good])

    # Model estimation
    m_type = model.lower()
    H_3x3: Optional[np.ndarray] = None
    mask: Optional[np.ndarray] = None

    if m_type == "homography":
        H, mask = cv2.findHomography(
            pts_a, pts_b, method=cv2.RANSAC, ransacReprojThreshold=RANSAC_THRESHOLD, maxIters=2000
        )
        if H is not None:
            H_3x3 = H
    elif m_type == "similarity":
        M, mask = cv2.estimateAffinePartial2D(
            pts_a, pts_b, method=cv2.RANSAC, ransacReprojThreshold=RANSAC_THRESHOLD, maxIters=2000
        )
        if M is not None:
            H_3x3 = np.vstack([M, [0.0, 0.0, 1.0]])
    else:  # "affine" default
        M, mask = cv2.estimateAffine2D(
            pts_a, pts_b, method=cv2.RANSAC, ransacReprojThreshold=RANSAC_THRESHOLD, maxIters=2000
        )
        if M is not None:
            H_3x3 = np.vstack([M, [0.0, 0.0, 1.0]])

    if H_3x3 is None or mask is None:
        result.error = f"RANSAC {m_type} estimation failed"
        result.status = "failed"
        return result

    inliers = int(mask.sum())
    result.inliers = inliers
    result.inlier_ratio = float(inliers) / float(len(good))

    if inliers < MIN_INLIERS:
        result.error = f"RANSAC inliers too low: {inliers}"
        result.status = "rejected"
        return result

    rmse = compute_reprojection_error(pts_a, pts_b, H_3x3, mask)
    result.reprojection_error_px = rmse

    # Sanity checks
    if not validate_transform_sanity(H_3x3, img_a.shape[:2]):
        result.error = "Transform failed geometric sanity checks (extreme scale, rotation, or displacement)"
        result.status = "rejected"
        return result

    if m_type == "homography":
        result.transform = H_3x3
    else:
        result.transform = H_3x3[:2, :]  # 2x3 for affine/similarity
    result.matrix = H_3x3.astype(float).tolist()
    result.success = True
    result.status = "accepted"

    # Optional debug visualization
    if save_debug_path:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(save_debug_path)), exist_ok=True)
            matches_mask = mask.ravel().tolist()
            debug_img = cv2.drawMatches(
                img_a, kp_a, img_b, kp_b, good, None,
                matchesMask=matches_mask,
                flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS
            )
            cv2.imwrite(save_debug_path, debug_img)
        except Exception:
            pass

    return result
