"""Stage 5 - match features.

Implements the brief's sequence for every candidate pair:

1. decode once and build an approximately 0.6 MP *matching copy*;
2. detect ORB (or AKAZE) keypoints;
3. brute-force Hamming k-NN match;
4. Lowe ratio filtering to drop ambiguous correspondences.

RANSAC happens in :mod:`edge_ortho.align.transform`, which also records inliers
and reprojection error.

Every step degrades gracefully: an unreadable frame, an empty descriptor set or
a pair with too few matches produces a *status* rather than an exception, so
one bad pair cannot abort a whole run.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


def matching_scale(width: int, height: int, target_megapixels: float) -> float:
    """Scale factor that brings a ``width x height`` image to ~``target_mp``.

    Never upscales: the result is clamped to ``(0, 1]``.
    """
    if width <= 0 or height <= 0 or target_megapixels <= 0:
        return 1.0
    current_mp = (width * height) / 1e6
    if current_mp <= target_megapixels:
        return 1.0
    return math.sqrt(target_megapixels / current_mp)


@dataclass
class FrameFeatures:
    frame_id: str
    path: str
    scale: float
    width: int
    height: int
    keypoints: list = field(default_factory=list)
    descriptors: np.ndarray | None = None
    elapsed_ms: float = 0.0
    error: str | None = None

    @property
    def count(self) -> int:
        return len(self.keypoints)


def load_matching_copy(path: str | Path, scale: float) -> tuple[np.ndarray, float] | None:
    """Decode an image and return ``(downscaled BGR copy, effective scale)``.

    Returns ``None`` when the file cannot be decoded. The *effective* scale is
    returned because ``IMREAD_REDUCED_COLOR_2`` performs part of the reduction
    inside the decoder: callers must record this value (not the requested one)
    so that matching-copy pixels can be converted back to original pixels
    correctly.
    """
    path = str(path)
    img = None
    effective = float(scale)
    # Ask libjpeg for a half-scale decode when we need a big reduction, which is
    # the cheapest way to get a small matching copy.
    if scale <= 0.55:
        img = cv2.imread(path, cv2.IMREAD_REDUCED_COLOR_2)
        if img is not None:
            effective = scale * 2.0  # remainder applied by the resize below
    if img is None:
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        effective = float(scale)
    if img is None:
        return None
    if effective >= 0.999:
        return img, 1.0
    new_w = max(1, round(img.shape[1] * effective))
    new_h = max(1, round(img.shape[0] * effective))
    out = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return out, float(scale)


def create_detector(kind: str = "orb", n_features: int = 3000):
    """Build a feature detector. Unknown kinds raise rather than silently default."""
    kind = (kind or "orb").lower()
    if kind == "orb":
        return cv2.ORB.create(
            nfeatures=int(n_features),
            scaleFactor=1.2,
            nlevels=8,
            edgeThreshold=19,
            fastThreshold=12,
        )
    if kind == "akaze":
        return cv2.AKAZE.create()
    raise ValueError(f"unsupported feature detector: {kind!r} (expected 'orb' or 'akaze')")


def detect_features(
    path: str | Path,
    frame_id: str,
    scale: float,
    detector,
    detector_name: str,
) -> FrameFeatures:
    """Detect keypoints on the matching copy of one frame."""
    import time

    t0 = time.perf_counter()
    loaded = load_matching_copy(path, scale)
    if loaded is None:
        return FrameFeatures(frame_id, str(path), scale, 0, 0, error="decode_failed")
    img, effective_scale = loaded
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    try:
        kps, desc = detector.detectAndCompute(gray, None)
    except cv2.error as exc:  # pragma: no cover - defensive
        return FrameFeatures(
            frame_id,
            str(path),
            effective_scale,
            img.shape[1],
            img.shape[0],
            error=f"detector_error: {exc}",
        )
    return FrameFeatures(
        frame_id=frame_id,
        path=str(path),
        scale=effective_scale,
        width=img.shape[1],
        height=img.shape[0],
        keypoints=list(kps or []),
        descriptors=desc,
        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
    )


@dataclass
class MatchResult:
    status: str
    raw_matches: int = 0
    ratio_matches: int = 0
    src_points: np.ndarray | None = None
    dst_points: np.ndarray | None = None
    error: str | None = None


def match_descriptors(
    src: FrameFeatures,
    dst: FrameFeatures,
    ratio_threshold: float = 0.75,
    min_matches: int = 18,
    detector_name: str = "orb",
) -> MatchResult:
    """k-NN match two descriptor sets and apply the Lowe ratio test."""
    if src.error or dst.error:
        return MatchResult("decode_failed", error=src.error or dst.error)
    if src.descriptors is None or dst.descriptors is None:
        return MatchResult("insufficient_keypoints")
    if src.count < 8 or dst.count < 8:
        return MatchResult("insufficient_keypoints")

    norm = cv2.NORM_HAMMING
    matcher = cv2.BFMatcher(norm, crossCheck=False)
    try:
        knn = matcher.knnMatch(src.descriptors, dst.descriptors, k=2)
    except cv2.error as exc:  # pragma: no cover - defensive
        return MatchResult("insufficient_matches", error=f"matcher_error: {exc}")

    good = []
    for pair in knn:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < ratio_threshold * n.distance:
            good.append(m)

    if len(good) < min_matches:
        return MatchResult("insufficient_matches", raw_matches=len(knn), ratio_matches=len(good))

    src_pts = np.float32([src.keypoints[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst_pts = np.float32([dst.keypoints[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    return MatchResult(
        status="ok",
        raw_matches=len(knn),
        ratio_matches=len(good),
        src_points=src_pts,
        dst_points=dst_pts,
    )
