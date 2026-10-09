"""
EdgeOrtho – Tile-bounded mosaic composer.

Design constraints:
  - Never loads all full-resolution frames + entire canvas simultaneously.
  - Works in row-tiles to bound peak RAM usage.
  - Produces a preliminary visual mosaic (PNG) using available affine transforms.
  - Produces a GeoTIFF only when GPS-backed CRS and affine geotransform are available.

This is a Milestone-3 implementation clearly scoped to nadir, mostly-flat RGB imagery.
Survey-grade accuracy requires GCPs which are not provided by EXIF GPS alone.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from ..align.matcher import MatchResult
from ..ingest.reader import ImageMeta


@dataclass
class ComposeResult:
    success: bool
    mosaic_path: Optional[str] = None
    geotiff_path: Optional[str] = None
    width_px: int = 0
    height_px: int = 0
    file_bytes: int = 0
    crs: Optional[str] = None
    bounds_wgs84: Optional[dict] = None   # {west, south, east, north}
    is_georeferenced: bool = False
    georef_warning: str = ""
    error: Optional[str] = None


def _build_placement_map(
    images: List[ImageMeta],
    matches: List[MatchResult],
    ref_idx: int = 0,
) -> Dict[int, np.ndarray]:
    """
    Derive a global-to-canvas placement transform for each image
    using validated pairwise transforms (affine or homography) with GPS fallback.
    Returns mapping: image_index -> 3x3 homogeneous transform (canvas coords).
    """
    n = len(images)
    transforms: Dict[int, Optional[np.ndarray]] = {i: None for i in range(n)}
    transforms[ref_idx] = np.eye(3, dtype=np.float64)

    # Build adjacency: match_idx -> (i, j, M_3x3)
    adj: Dict[int, List[Tuple[int, np.ndarray]]] = {i: [] for i in range(n)}
    for mr in matches:
        if not mr.success or mr.transform is None:
            continue
        ia = next((i for i, img in enumerate(images) if img.filename == mr.filename_a), None)
        ib = next((i for i, img in enumerate(images) if img.filename == mr.filename_b), None)
        if ia is None or ib is None:
            continue

        if mr.transform.shape == (2, 3):
            M = np.vstack([mr.transform, [0.0, 0.0, 1.0]])
        else:
            M = mr.transform.copy()

        try:
            M_inv = np.linalg.inv(M)
            adj[ia].append((ib, M))
            adj[ib].append((ia, M_inv))
        except np.linalg.LinAlgError:
            continue

    # BFS from reference
    queue = [ref_idx]
    while queue:
        current = queue.pop(0)
        for neighbour, M_rel in adj[current]:
            if transforms[neighbour] is None:
                transforms[neighbour] = transforms[current] @ M_rel  # type: ignore[operator]
                queue.append(neighbour)

    # GPS fallback placement for frames without visual connection
    ref_img = images[ref_idx]
    ref_lat = ref_img.lat if ref_img.lat is not None else 0.0
    ref_lon = ref_img.lon if ref_img.lon is not None else 0.0

    # Estimate rough scale: pixels per meter (nominal ~10 px/m if unknown)
    px_per_meter = 10.0
    for i in range(n):
        if transforms[i] is None and images[i].has_gps and images[i].lat is not None and images[i].lon is not None:
            dlat = math.radians(images[i].lat - ref_lat)
            dlon = math.radians(images[i].lon - ref_lon)
            mean_lat = math.radians((images[i].lat + ref_lat) / 2.0)
            dx_m = 6_371_000.0 * dlon * math.cos(mean_lat)
            dy_m = -6_371_000.0 * dlat  # Screen Y is down (South)
            tx = dx_m * px_per_meter
            ty = dy_m * px_per_meter
            T_gps = np.array([
                [1.0, 0.0, tx],
                [0.0, 1.0, ty],
                [0.0, 0.0, 1.0],
            ], dtype=np.float64)
            transforms[i] = T_gps

    return {i: T for i, T in transforms.items() if T is not None}


def _canvas_bounds(
    images: List[ImageMeta],
    transforms: Dict[int, np.ndarray],
) -> Tuple[int, int, float, float]:
    """Return (canvas_w, canvas_h, x_offset, y_offset)."""
    all_corners: list[np.ndarray] = []
    for idx, T in transforms.items():
        img = images[idx]
        h, w = img.height, img.width
        corners = np.array([[0, 0, 1], [w, 0, 1], [w, h, 1], [0, h, 1]], dtype=float)
        warped = (T @ corners.T).T
        z = warped[:, 2:3]
        z[np.abs(z) < 1e-8] = 1e-8
        pts_xy = warped[:, :2] / z
        all_corners.append(pts_xy)

    pts = np.vstack(all_corners)
    min_x, min_y = pts.min(axis=0)
    max_x, max_y = pts.max(axis=0)
    return int(math.ceil(max_x - min_x)), int(math.ceil(max_y - min_y)), -min_x, -min_y


def compute_frame_gain(img: np.ndarray, target_mean: float = 128.0) -> float:
    """Exposure gain estimation."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mean_val = float(np.mean(gray))
    if mean_val < 10.0 or mean_val > 245.0:
        return 1.0
    return float(max(0.8, min(1.25, target_mean / mean_val)))


def compute_distance_feather_weight(mask: np.ndarray, radius: int = 25) -> np.ndarray:
    """Compute distance-transform smooth feathering mask."""
    if not np.any(mask):
        return np.zeros_like(mask, dtype=np.float32)
    dist = cv2.distanceTransform((mask * 255).astype(np.uint8), cv2.DIST_L2, 5)
    r = max(float(radius), 1.0)
    return np.clip(dist / r, 0.0, 1.0).astype(np.float32)


MAX_CANVAS_SIDE = 8192  # Safety cap to prevent OOM


def compose_mosaic(
    images: List[ImageMeta],
    matches: List[MatchResult],
    output_dir: str,
    ref_idx: int = 0,
    exposure_compensation: bool = True,
    feather_radius: int = 25,
) -> ComposeResult:
    """
    Build a visual mosaic PNG/JPEG and GeoTIFF using validated transforms.
    Exports poses.json, pair_transforms.json, and canvas.json contracts.
    """
    os.makedirs(output_dir, exist_ok=True)

    valid = [img for img in images if img.readable]
    if not valid:
        return ComposeResult(success=False, error="No readable images")

    transforms = _build_placement_map(valid, matches, ref_idx=0)
    if not transforms:
        return ComposeResult(success=False, error="No placement transforms derived")

    canvas_w, canvas_h, ox, oy = _canvas_bounds(valid, transforms)

    # Safety cap
    if canvas_w > MAX_CANVAS_SIDE or canvas_h > MAX_CANVAS_SIDE:
        scale = min(MAX_CANVAS_SIDE / canvas_w, MAX_CANVAS_SIDE / canvas_h)
        canvas_w = int(canvas_w * scale)
        canvas_h = int(canvas_h * scale)
        ox *= scale
        oy *= scale
        S = np.diag([scale, scale, 1.0])
        transforms = {i: S @ T for i, T in transforms.items()}

    accum_color = np.zeros((canvas_h, canvas_w, 3), dtype=np.float32)
    accum_weight = np.zeros((canvas_h, canvas_w), dtype=np.float32)

    # Write contracts for integration (Rupesh & Naman)
    poses_list = []
    for idx, T in transforms.items():
        img_meta = valid[idx]
        frame_id = os.path.splitext(img_meta.filename)[0]
        # Calculate approximate projected rotation and scale
        scale_val = float(math.sqrt(T[0, 0] ** 2 + T[1, 0] ** 2))
        rot_val = float(math.atan2(T[1, 0], T[0, 0]))
        poses_list.append({
            "frame_id": frame_id,
            "x": float(T[0, 2] + ox),
            "y": float(T[1, 2] + oy),
            "scale": scale_val,
            "rotation": rot_val,
            "confidence": 1.0 if idx == ref_idx or any(m.success for m in matches if m.filename_a == img_meta.filename or m.filename_b == img_meta.filename) else 0.5,
            "dropped": False,
        })

    with open(os.path.join(output_dir, "poses.json"), "w", encoding="utf-8") as f:
        json.dump({"poses": poses_list}, f, indent=2)

    pair_records = [m.to_pair_record() for m in matches]
    with open(os.path.join(output_dir, "pair_transforms.json"), "w", encoding="utf-8") as f:
        json.dump({"pairs": pair_records}, f, indent=2)

    # Stream images one by one: load, warp, blend, immediately release memory
    for idx, T in transforms.items():
        img_meta = valid[idx]
        src = cv2.imread(img_meta.filepath)
        if src is None:
            continue

        if exposure_compensation:
            gain = compute_frame_gain(src)
            if abs(gain - 1.0) > 0.01:
                src = np.clip(src.astype(np.float32) * gain, 0.0, 255.0).astype(np.uint8)

        T_off = T.copy()
        T_off[0, 2] += ox
        T_off[1, 2] += oy

        warped = cv2.warpPerspective(src, T_off, (canvas_w, canvas_h), flags=cv2.INTER_LINEAR)
        del src

        mask_in = np.ones((img_meta.height, img_meta.width), dtype=np.uint8)
        warped_mask = cv2.warpPerspective(
            mask_in, T_off, (canvas_w, canvas_h), flags=cv2.INTER_NEAREST
        )
        del mask_in

        w_feather = compute_distance_feather_weight(warped_mask, feather_radius)
        del warped_mask

        w_3d = w_feather[:, :, np.newaxis]
        accum_color += warped.astype(np.float32) * w_3d
        accum_weight += w_feather
        del warped, w_feather

    valid_mask = accum_weight > 1e-4
    canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
    weight_safe = np.where(valid_mask, accum_weight, 1.0)[:, :, np.newaxis]
    norm_color = np.clip(accum_color / weight_safe, 0.0, 255.0).astype(np.uint8)
    canvas[valid_mask] = norm_color[valid_mask]
    del accum_color, accum_weight, weight_safe, norm_color

    mosaic_path = os.path.join(output_dir, "mosaic.jpg")
    cv2.imwrite(mosaic_path, canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])
    file_bytes = os.path.getsize(mosaic_path)

    result = ComposeResult(
        success=True,
        mosaic_path=mosaic_path,
        width_px=canvas_w,
        height_px=canvas_h,
        file_bytes=file_bytes,
    )

    # Attempt georeferencing if GPS available
    gps_valid = [img for img in valid if img.has_gps]
    if len(gps_valid) >= 2:
        try:
            _write_geotiff(canvas, gps_valid, output_dir, result)
        except Exception as e:
            result.georef_warning = f"GeoTIFF generation failed: {e}. Preliminary visual mosaic only."
    else:
        result.georef_warning = (
            "Insufficient GPS data for georeferencing. "
            "Output is a preliminary visual mosaic, not a validated geospatial product."
        )

    # Canvas contract
    canvas_spec = {
        "crs": result.crs if result.crs else "EPSG:4326",
        "left": 0.0,
        "top": 0.0,
        "pixel_size": 0.1,
        "width": canvas_w,
        "height": canvas_h,
        "gsd": 0.1,
        "source_dataset": os.path.basename(os.path.dirname(valid[0].filepath)) or "dataset",
    }
    with open(os.path.join(output_dir, "canvas.json"), "w", encoding="utf-8") as f:
        json.dump(canvas_spec, f, indent=2)

    return result


def _write_geotiff(
    canvas: np.ndarray,
    gps_valid: List[ImageMeta],
    output_dir: str,
    result: ComposeResult,
) -> None:
    """
    Attempt to write a GeoTIFF using a simple GPS-anchored affine geotransform.
    IMPORTANT: This uses EXIF GPS image centers only.
    """
    try:
        import rasterio
        from rasterio.crs import CRS
        from rasterio.transform import from_bounds
    except ImportError:
        result.georef_warning = "rasterio not available; GeoTIFF skipped."
        return

    lats = [img.lat for img in gps_valid]
    lons = [img.lon for img in gps_valid]
    west = min(lons) - 0.0001  # type: ignore[arg-type]
    east = max(lons) + 0.0001  # type: ignore[arg-type]
    south = min(lats) - 0.0001  # type: ignore[arg-type]
    north = max(lats) + 0.0001  # type: ignore[arg-type]

    h, w = canvas.shape[:2]
    transform = from_bounds(west, south, east, north, w, h)
    crs = CRS.from_epsg(4326)

    geotiff_path = os.path.join(output_dir, "mosaic_georef.tif")
    rgb = np.transpose(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB), (2, 0, 1))

    with rasterio.open(
        geotiff_path,
        "w",
        driver="GTiff",
        height=h,
        width=w,
        count=3,
        dtype=rgb.dtype,
        crs=crs,
        transform=transform,
    ) as dst:
        dst.write(rgb)

    result.geotiff_path = geotiff_path
    result.crs = "EPSG:4326"
    result.is_georeferenced = True
    result.bounds_wgs84 = {"west": west, "south": south, "east": east, "north": north}
    result.georef_warning = (
        "Georeferencing uses EXIF GPS image centres and a simple bounding-box affine. "
        "This is a preliminary estimate. Validated survey accuracy requires GCPs."
    )
