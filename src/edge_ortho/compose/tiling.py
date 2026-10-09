"""Tile-by-tile bounded memory composition engine."""

import math
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass

import cv2
import numpy as np

from ..align.global_solve import GlobalPose
from ..ingest.models import FrameRecord
from .blend import blend_accumulator, finalize_tile
from .exposure import apply_gain, compute_frame_luminance_gain


@dataclass
class CanvasLayout:
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    width_px: int
    height_px: int
    frame_boxes: dict[
        str, tuple[float, float, float, float]
    ]  # frame_id -> (min_x, min_y, max_x, max_y)
    frame_transforms: dict[str, np.ndarray]  # frame_id -> 3x3 transform to shifted canvas


@dataclass
class TileResult:
    tile_index: tuple[int, int]  # (row, col)
    bounds_px: tuple[int, int, int, int]  # (x0, y0, x1, y1) in canvas coordinates
    rgb: np.ndarray  # (H, W, 3) uint8
    alpha: np.ndarray  # (H, W) uint8
    is_empty: bool


def compute_canvas_layout(
    records: Sequence[FrameRecord],
    poses: dict[str, GlobalPose],
) -> CanvasLayout:
    """
    Computes global bounding box across all projected frame corners,
    shifts origin to (0, 0), and computes bounding boxes for spatial indexing.
    """
    record_map = {r.frame_id: r for r in records}
    frame_boxes = {}
    shifted_transforms = {}

    all_corners_x = []
    all_corners_y = []

    # 1. Project 4 corners of each frame
    projected_corners = {}
    for fid, pose in poses.items():
        rec = record_map.get(fid)
        if not rec:
            continue
        w, h = rec.width, rec.height
        corners = np.array(
            [
                [0.0, 0.0, 1.0],
                [w, 0.0, 1.0],
                [w, h, 1.0],
                [0.0, h, 1.0],
            ],
            dtype=np.float64,
        )

        proj = corners @ pose.h_native_to_canvas.T
        z = proj[:, 2:3]
        z[np.abs(z) < 1e-8] = 1e-8
        pts_xy = proj[:, :2] / z
        projected_corners[fid] = pts_xy

        all_corners_x.extend(pts_xy[:, 0])
        all_corners_y.extend(pts_xy[:, 1])

    min_x = float(min(all_corners_x))
    min_y = float(min(all_corners_y))
    max_x = float(max(all_corners_x))
    max_y = float(max(all_corners_y))

    width_px = int(math.ceil(max_x - min_x))
    height_px = int(math.ceil(max_y - min_y))

    # Shift matrix: canvas origin at (0, 0)
    T_shift = np.array([[1.0, 0.0, -min_x], [0.0, 1.0, -min_y], [0.0, 0.0, 1.0]], dtype=np.float64)

    for fid, pts_xy in projected_corners.items():
        # Shifted points
        shifted_pts = pts_xy - np.array([min_x, min_y])
        fx0 = float(np.min(shifted_pts[:, 0]))
        fy0 = float(np.min(shifted_pts[:, 1]))
        fx1 = float(np.max(shifted_pts[:, 0]))
        fy1 = float(np.max(shifted_pts[:, 1]))
        frame_boxes[fid] = (fx0, fy0, fx1, fy1)

        # Shifted 3x3 transform
        H_orig = poses[fid].h_native_to_canvas
        shifted_transforms[fid] = T_shift @ H_orig

    return CanvasLayout(
        min_x=min_x,
        min_y=min_y,
        max_x=max_x,
        max_y=max_y,
        width_px=width_px,
        height_px=height_px,
        frame_boxes=frame_boxes,
        frame_transforms=shifted_transforms,
    )


def compose_tiles_streaming(
    records: Sequence[FrameRecord],
    layout: CanvasLayout,
    tile_size: int = 2048,
    feather_radius: int = 25,
    exposure_compensation: bool = True,
    target_luminance: float = 128.0,
    on_first_tile_callback: Callable | None = None,
) -> Generator[TileResult, None, None]:
    """
    Tile-by-tile composition generator.
    Processes the orthomosaic in strictly memory-bounded chunks of (tile_size x tile_size),
    warping and accumulating only intersecting frames.
    Yields TileResult for each grid cell.
    """
    record_map = {r.frame_id: r for r in records}
    num_cols = int(math.ceil(layout.width_px / tile_size))
    num_rows = int(math.ceil(layout.height_px / tile_size))

    # Pre-calculate gains if exposure compensation is enabled
    frame_gains = {}
    if exposure_compensation:
        for r in records:
            try:
                # Read small thumbnail to compute luminance
                img = cv2.imread(str(r.path))
                if img is not None:
                    frame_gains[r.frame_id] = compute_frame_luminance_gain(img, target_luminance)
            except Exception:
                frame_gains[r.frame_id] = 1.0

    first_tile_notified = False

    for r_idx in range(num_rows):
        for c_idx in range(num_cols):
            x0 = c_idx * tile_size
            y0 = r_idx * tile_size
            x1 = min(x0 + tile_size, layout.width_px)
            y1 = min(y0 + tile_size, layout.height_px)
            tw = x1 - x0
            th = y1 - y0

            # Find frames intersecting this tile box
            intersecting_fids = []
            for fid, (bx0, by0, bx1, by1) in layout.frame_boxes.items():
                if not (bx1 < x0 or bx0 > x1 or by1 < y0 or by0 > y1):
                    intersecting_fids.append(fid)

            if not intersecting_fids:
                # Empty tile
                blank_rgb = np.zeros((th, tw, 3), dtype=np.uint8)
                blank_alpha = np.zeros((th, tw), dtype=np.uint8)
                yield TileResult(
                    tile_index=(r_idx, c_idx),
                    bounds_px=(x0, y0, x1, y1),
                    rgb=blank_rgb,
                    alpha=blank_alpha,
                    is_empty=True,
                )
                continue

            # Initialize accumulators for this tile
            accum_color = np.zeros((th, tw, 3), dtype=np.float32)
            accum_weight = np.zeros((th, tw), dtype=np.float32)

            # Local tile offset matrix: shifts global canvas (x0, y0) to tile local (0, 0)
            T_tile = np.array([[1.0, 0.0, -x0], [0.0, 1.0, -y0], [0.0, 0.0, 1.0]], dtype=np.float64)

            for fid in intersecting_fids:
                rec = record_map[fid]
                try:
                    img = cv2.imread(str(rec.path))
                    if img is None:
                        continue

                    if exposure_compensation and fid in frame_gains:
                        img = apply_gain(img, frame_gains[fid])

                    # Composite transform: native image pixels -> tile local pixels
                    H_local = T_tile @ layout.frame_transforms[fid]

                    # Warp image and mask into tile
                    # Check if perspective or affine
                    is_perspective = (
                        abs(H_local[2, 0]) > 1e-6
                        or abs(H_local[2, 1]) > 1e-6
                        or abs(H_local[2, 2] - 1.0) > 1e-6
                    )

                    if is_perspective:
                        warped_img = cv2.warpPerspective(
                            img, H_local, (tw, th), flags=cv2.INTER_LINEAR
                        )
                        mask_in = np.ones((img.shape[0], img.shape[1]), dtype=np.uint8)
                        warped_mask = cv2.warpPerspective(
                            mask_in, H_local, (tw, th), flags=cv2.INTER_NEAREST
                        )
                    else:
                        M_2x3 = H_local[:2, :]
                        warped_img = cv2.warpAffine(img, M_2x3, (tw, th), flags=cv2.INTER_LINEAR)
                        mask_in = np.ones((img.shape[0], img.shape[1]), dtype=np.uint8)
                        warped_mask = cv2.warpAffine(
                            mask_in, M_2x3, (tw, th), flags=cv2.INTER_NEAREST
                        )

                    blend_accumulator(
                        accum_color, accum_weight, warped_img, warped_mask, feather_radius
                    )

                    del img, warped_img, warped_mask, mask_in
                except Exception:
                    continue

            # Finalize tile
            rgb_tile, alpha_tile = finalize_tile(accum_color, accum_weight)
            del accum_color, accum_weight

            res = TileResult(
                tile_index=(r_idx, c_idx),
                bounds_px=(x0, y0, x1, y1),
                rgb=rgb_tile,
                alpha=alpha_tile,
                is_empty=False,
            )

            if not first_tile_notified:
                first_tile_notified = True
                if on_first_tile_callback:
                    on_first_tile_callback(res)

            yield res
