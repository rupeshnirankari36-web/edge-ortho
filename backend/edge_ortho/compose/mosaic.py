"""Stage 7 - compose the output tile by tile with bounded memory.

This is the brief's core memory argument:

    "Tile-by-tile composition: prevents the complete image collection and full
    output canvas from occupying memory simultaneously."
    "Warp only images intersecting the active tile."

The implementation keeps that promise literally:

* the output canvas is never allocated as one array - only one tile at a time;
* at most ``decode_cache_size`` decoded frames are held, and only for the tile
  currently being written;
* a frame is decoded, its contribution to this tile is warped in, and it is then
  evicted, so peak memory is roughly ``tile buffers + cache x one frame`` and
  does not grow with the number of images.

Blending uses a per-frame feathered weight (distance to the frame edge) so seams
are soft, and optional gain compensation matches overlapping frames' brightness
to reduce visible exposure steps.

Time-to-first-tile is measured here because it is the honest "first useful map"
number the brief asks for.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from ..contracts import FrameRecord, GlobalPose


@dataclass
class ComposeStats:
    tiles_total: int = 0
    tiles_written: int = 0
    frames_composed: int = 0
    frames_skipped: int = 0
    frames_failed: int = 0
    decode_count: int = 0
    peak_cache_entries: int = 0
    time_to_first_tile_s: float | None = None
    compose_seconds: float = 0.0
    canvas_megapixels: float = 0.0
    longest_frame_edge_decoded: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tiles_total": self.tiles_total,
            "tiles_written": self.tiles_written,
            "frames_composed": self.frames_composed,
            "frames_skipped": self.frames_skipped,
            "frames_failed": self.frames_failed,
            "decodes": self.decode_count,
            "peak_cache_entries": self.peak_cache_entries,
            "time_to_first_tile_s": self.time_to_first_tile_s,
            "compose_seconds": self.compose_seconds,
            "canvas_megapixels": self.canvas_megapixels,
            "errors": self.errors[:20],
        }


class FrameCache:
    """Tiny LRU of decoded frames, bounded by ``capacity``."""

    def __init__(self, capacity: int = 2, max_decode_side: int | None = None):
        self.capacity = max(1, capacity)
        self.max_decode_side = max_decode_side
        self._items: dict[str, np.ndarray] = {}
        self._order: list[str] = []
        self.decodes = 0
        self.peak = 0

    def get(self, frame: FrameRecord) -> np.ndarray | None:
        key = frame.frame_id
        if key in self._items:
            self._order.remove(key)
            self._order.append(key)
            return self._items[key]
        img = self._decode(frame)
        self.decodes += 1
        if img is None:
            return None
        self._items[key] = img
        self._order.append(key)
        while len(self._order) > self.capacity:
            oldest = self._order.pop(0)
            self._items.pop(oldest, None)
        self.peak = max(self.peak, len(self._items))
        return img

    def _decode(self, frame: FrameRecord) -> np.ndarray | None:
        path = Path(frame.path)
        if not path.exists():
            return None
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            return None
        h, w = img.shape[:2]
        longest = max(h, w)
        if self.max_decode_side and longest > self.max_decode_side:
            f = self.max_decode_side / longest
            img = cv2.resize(img, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA)
        return img


def _render_transform(pose: GlobalPose, frame: FrameRecord, img_shape: tuple[int, int]) -> np.ndarray:
    """Map decoded-image pixels to canvas pixels for one frame.

    The pose is defined on the *original* frame pixels. If the decoded copy was
    resized, the scale is folded in so warping stays correct.
    """
    m = np.array(pose.matrix(), dtype=np.float64)
    if not frame.width or not frame.height:
        return m
    decoded_h, decoded_w = img_shape
    kx = decoded_w / float(frame.width)
    ky = decoded_h / float(frame.height)
    if abs(kx - 1.0) < 1e-9 and abs(ky - 1.0) < 1e-9:
        return m
    s = np.array([[kx, 0.0, 0.0], [0.0, ky, 0.0], [0.0, 0.0, 1.0]])
    return m @ s


def _quad_bounds(m: np.ndarray, w: int, h: int) -> tuple[float, float, float, float]:
    pts = np.array([[0, 0, 1], [w, 0, 1], [w, h, 1], [0, h, 1]], dtype=np.float64)
    out = pts @ m.T
    out = out[:, :2] / out[:, 2:3]
    return float(out[:, 0].min()), float(out[:, 1].min()), float(out[:, 0].max()), float(out[:, 1].max())


def _feather_weight(w: int, h: int, blend_px: int) -> np.ndarray:
    """Per-pixel weight that fades out near the image border.

    Uses the distance to the nearest edge via two 1-D ramps, which is cheap and
    keeps the interiors fully weighted so the mosaic is not darkened where
    several frames overlap.
    """
    blend = max(1, min(blend_px, w // 2, h // 2))
    ramp_x = np.minimum(np.arange(w) + 1, w - np.arange(w))
    ramp_y = np.minimum(np.arange(h) + 1, h - np.arange(h))
    wx = np.clip(ramp_x / blend, 0.0, 1.0)
    wy = np.clip(ramp_y / blend, 0.0, 1.0)
    return np.minimum.outer(wy, wx).astype(np.float32)


def _marker_transform(m: np.ndarray, ox: float, oy: float, tile: int) -> np.ndarray:
    """Affine that maps an image directly into ``tile``-local coordinates."""
    t = np.array([[1.0, 0.0, -ox], [0.0, 1.0, -oy], [0.0, 0.0, 1.0]])
    return t @ m


def estimate_exposure_gains(
    frames: list[FrameRecord],
    poses: dict[str, GlobalPose],
    max_frames: int = 24,
    sample_px: int = 128,
) -> dict[str, float]:
    """Cheap per-frame brightness gain from a downscaled centre sample.

    Deliberately approximate: it reduces visible exposure steps between
    overlapping frames without pretending to be radiometric calibration.
    """
    gains: dict[str, float] = {}
    medians: dict[str, float] = {}
    for frame in frames:
        pose = poses.get(frame.frame_id)
        if pose is None:
            continue
        m = np.array(pose.matrix(), dtype=np.float64)
        quad = np.array([[0, 0, 1], [frame.width or 0, 0, 1], [0, frame.height or 0, 1]], dtype=np.float64)
        proj = quad @ m.T
        scale = math.hypot(m[0, 0], m[1, 0])
        if scale <= 0:
            continue
        w = max(8, round(480 * scale))
        h = max(8, round(270 * scale))
        img = cv2.imread(frame.path, cv2.IMREAD_REDUCED_COLOR_8)
        if img is None:
            continue
        small = cv2.resize(img, (sample_px, sample_px), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        medians[frame.frame_id] = float(np.median(gray))
        _ = (proj, w, h)
    if not medians:
        return gains
    target = float(np.median(list(medians.values())))
    for fid, value in medians.items():
        if value <= 1.0:
            gains[fid] = 1.0
            continue
        gains[fid] = float(np.clip(target / value, 0.8, 1.25))
    return gains


def compose_mosaic(
    frames: list[FrameRecord],
    poses: dict[str, GlobalPose],
    canvas_width: int,
    canvas_height: int,
    tile_size: int = 2048,
    decode_cache_size: int = 2,
    max_decode_side: int | None = None,
    seam_blend_px: int = 48,
    gains: dict[str, float] | None = None,
    sink: Callable[[int, int, np.ndarray], None] | None = None,
    on_tile: Callable[[int, int, int, int], None] | None = None,
    on_first_tile: Callable[[float], None] | None = None,
    memory_check: Callable[[], None] | None = None,
    collect: bool = False,
) -> tuple[dict[tuple[int, int], np.ndarray], ComposeStats]:
    """Compose the mosaic tile by tile.

    Finished RGBA tiles are handed to ``sink(tile_x, tile_y, rgba)`` and then
    dropped, so the caller can stream them into a windowed raster write without
    ever allocating the full canvas. ``collect=True`` retains them instead, which
    is only used by tests on small canvases.
    """
    stats = ComposeStats(canvas_megapixels=canvas_width * canvas_height / 1e6)
    gains = gains or {}
    cache = FrameCache(decode_cache_size, max_decode_side=max_decode_side)

    tiles_x = math.ceil(canvas_width / tile_size)
    tiles_y = math.ceil(canvas_height / tile_size)
    stats.tiles_total = tiles_x * tiles_y

    # --- which frames touch which tile (computed from the poses only) ------
    placements: list[tuple[FrameRecord, np.ndarray, np.ndarray | None, float, float, float, float]] = []
    for frame in frames:
        pose = poses.get(frame.frame_id)
        if pose is None or not frame.width or not frame.height:
            stats.frames_skipped += 1
            continue
        m = np.array(pose.matrix(), dtype=np.float64)
        x0, y0, x1, y1 = _quad_bounds(m, frame.width, frame.height)
        if x1 < 0 or y1 < 0 or x0 > canvas_width or y0 > canvas_height:
            stats.frames_skipped += 1
            continue
        placements.append((frame, m, None, x0, y0, x1, y1))

    covered = np.zeros((tiles_y, tiles_x), dtype=bool)
    for _f, _m, _w, x0, y0, x1, y1 in placements:
        tx0 = max(0, int(x0 // tile_size))
        tx1 = min(tiles_x - 1, int(x1 // tile_size))
        ty0 = max(0, int(y0 // tile_size))
        ty1 = min(tiles_y - 1, int(y1 // tile_size))
        for ty in range(ty0, ty1 + 1):
            for tx in range(tx0, tx1 + 1):
                covered[ty, tx] = True

    tiles: dict[tuple[int, int], np.ndarray] = {}
    t_start = time.perf_counter()

    for ty in range(tiles_y):
        for tx in range(tiles_x):
            if not covered[ty, tx]:
                continue
            ox, oy = tx * tile_size, ty * tile_size
            tw = min(tile_size, canvas_width - ox)
            th = min(tile_size, canvas_height - oy)
            acc = np.zeros((th, tw, 3), dtype=np.float32)
            wsum = np.zeros((th, tw), dtype=np.float32)

            used_here = 0
            for frame, _m, _w, x0, y0, x1, y1 in placements:
                # bounding-box test against this tile before doing any work
                if x1 < ox or y1 < oy or x0 > ox + tw or y0 > oy + th:
                    continue
                img = cache.get(frame)
                if img is None:
                    stats.frames_failed += 1
                    if len(stats.errors) < 20:
                        stats.errors.append(f"{frame.filename}: decode failed")
                    continue
                stats.longest_frame_edge_decoded = max(
                    stats.longest_frame_edge_decoded, max(img.shape[:2])
                )
                rt = _render_transform(pose_of(poses, frame), frame, img.shape[:2])
                local = _marker_transform(rt, ox, oy, tile_size)
                warped = cv2.warpPerspective(
                    img,
                    local,
                    (tw, th),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=(0, 0, 0),
                )
                # OpenCV decodes BGR; the raster contract and preview writer use
                # RGB. Convert before blending so exported colours match the
                # uploaded photographs instead of swapping red and blue.
                warped = cv2.cvtColor(warped, cv2.COLOR_BGR2RGB)
                mask = cv2.warpPerspective(
                    np.ones(img.shape[:2], dtype=np.uint8),
                    local,
                    (tw, th),
                    flags=cv2.INTER_NEAREST,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=0,
                )
                if not mask.any():
                    continue
                weight = _feather_weight(img.shape[1], img.shape[0], seam_blend_px)
                weight_t = cv2.warpPerspective(
                    weight,
                    local,
                    (tw, th),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=0.0,
                )
                weight_t *= (mask > 0).astype(np.float32)

                gain = gains.get(frame.frame_id, 1.0)
                if gain != 1.0:
                    warped = np.clip(warped.astype(np.float32) * gain, 0, 255)
                acc += warped.astype(np.float32) * weight_t[:, :, None]
                wsum += weight_t
                used_here += 1

            if not wsum.any():
                continue
            safe = np.where(wsum > 1e-6, wsum, 1.0)
            rgb = np.clip(acc / safe[:, :, None], 0, 255).astype(np.uint8)
            alpha = (np.clip(wsum, 0.0, 1.0) * 255).astype(np.uint8)
            rgba = np.dstack([rgb, alpha])
            if sink is not None:
                sink(tx, ty, rgba)
            if collect:
                tiles[(tx, ty)] = rgba

            if used_here:
                stats.frames_composed = max(stats.frames_composed, used_here)
            stats.tiles_written += 1
            if stats.time_to_first_tile_s is None:
                stats.time_to_first_tile_s = time.perf_counter() - t_start
                if on_first_tile:
                    on_first_tile(stats.time_to_first_tile_s)
            if on_tile:
                on_tile(tx, ty, stats.tiles_written, stats.tiles_total)
            if memory_check:
                memory_check()

    stats.compose_seconds = time.perf_counter() - t_start
    stats.decode_count = cache.decodes
    stats.peak_cache_entries = cache.peak
    return tiles, stats


def pose_of(poses: dict[str, GlobalPose], frame: FrameRecord) -> GlobalPose:
    return poses[frame.frame_id]
