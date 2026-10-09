"""Phase 2 public contracts and output pipeline.

The module consumes only serializable pose/canvas JSON. Rendering is supplied
as a callback so Abhyuday's private CV implementation is never imported.
Composition writes one tile window at a time and emits metrics events.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import Affine, from_bounds
from rasterio.warp import calculate_default_transform, reproject, transform_bounds
from rasterio.windows import Window

from .geo_export import build_manifest, convert_to_cog, write_geotiff


@dataclass(frozen=True)
class PoseRecord:
    frame_id: str
    x: float
    y: float
    scale: float = 1.0
    rotation: float = 0.0
    confidence: float = 0.0
    dropped: bool = False


@dataclass(frozen=True)
class CanvasSpec:
    crs: str
    left: float
    top: float
    pixel_size: float
    width: int
    height: int
    gsd: float
    source_dataset: str

    @property
    def transform(self) -> Affine:
        return Affine(self.pixel_size, 0, self.left, 0, -self.pixel_size, self.top)


def _require(mapping: dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise ValueError(f"missing required field: {key}")
    return mapping[key]


def load_pose_contract(path: str | Path) -> list[PoseRecord]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("poses", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        raise ValueError("poses.json must contain a non-empty poses list")
    result: list[PoseRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each pose must be an object")
        result.append(PoseRecord(
            frame_id=str(_require(row, "frame_id")),
            x=float(_require(row, "x")),
            y=float(_require(row, "y")),
            scale=float(row.get("scale", 1.0)),
            rotation=float(row.get("rotation", 0.0)),
            confidence=float(row.get("confidence", 0.0)),
            dropped=bool(row.get("dropped", False)),
        ))
    return result


def load_canvas_contract(path: str | Path) -> CanvasSpec:
    row = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise ValueError("canvas.json must be an object")
    return CanvasSpec(
        crs=str(_require(row, "crs")),
        left=float(_require(row, "left")),
        top=float(_require(row, "top")),
        pixel_size=float(_require(row, "pixel_size")),
        width=int(_require(row, "width")),
        height=int(_require(row, "height")),
        gsd=float(_require(row, "gsd")),
        source_dataset=str(_require(row, "source_dataset")),
    )


def iter_tile_windows(canvas: CanvasSpec, tile_size: int = 2048) -> Iterator[Window]:
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")
    for row in range(0, canvas.height, tile_size):
        for col in range(0, canvas.width, tile_size):
            yield Window(col, row, min(tile_size, canvas.width - col), min(tile_size, canvas.height - row))


def compose_to_geotiff(
    canvas: CanvasSpec,
    output_path: str | Path,
    render_tile: Callable[[Window, CanvasSpec], np.ndarray],
    *,
    tile_size: int = 2048,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    nodata: int = 0,
) -> tuple[Path, list[dict[str, Any]]]:
    """Write a raster one window at a time; render_tile owns frame access."""
    events: list[dict[str, Any]] = []
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    first = True
    profile = {
        "driver": "GTiff", "height": canvas.height, "width": canvas.width,
        "count": 4, "dtype": "uint8", "crs": canvas.crs, "transform": canvas.transform,
        "nodata": nodata, "compress": "deflate", "tiled": True,
        "blockxsize": min(tile_size, 4096), "blockysize": min(tile_size, 4096),
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(output, "w", **profile) as dst:
        for window in iter_tile_windows(canvas, tile_size):
            tile = np.asarray(render_tile(window, canvas))
            expected = (4, int(window.height), int(window.width))
            if tile.shape != expected or tile.dtype != np.uint8:
                raise ValueError(f"render_tile returned {tile.shape}/{tile.dtype}; expected {expected}/uint8")
            dst.write(tile, window=window)
            event = {"event": "first_tile" if first else "tile_written", "row": int(window.row_off), "col": int(window.col_off), "width": int(window.width), "height": int(window.height)}
            events.append(event)
            if on_event:
                on_event(event)
            first = False
    final = {"event": "final_output", "path": str(output), "bytes": output.stat().st_size}
    events.append(final)
    if on_event:
        on_event(final)
    return output, events


def _tile_xy(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat = max(-85.05112878, min(85.05112878, lat))
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def _xyz_bounds_wgs84(x: int, y: int, zoom: int) -> tuple[float, float, float, float]:
    n = 2**zoom
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return west, south, east, north


def generate_xyz_tiles(
    raster_path: str | Path,
    tile_dir: str | Path,
    *,
    zoom_min: int,
    zoom_max: int,
    tile_size: int = 256,
) -> dict[str, Any]:
    """Generate XYZ PNG tiles from the final georeferenced raster.

    The source is reprojected to Web Mercator for each requested zoom. Zoom
    bounds and tile counts are computed from the source raster bounds.
    """
    if zoom_min < 0 or zoom_max < zoom_min:
        raise ValueError("invalid zoom range")
    output_dir = Path(tile_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with rasterio.open(raster_path) as src:
        dst_transform, dst_width, dst_height = calculate_default_transform(src.crs, "EPSG:3857", src.width, src.height, *src.bounds)
        source = src.read()
        reprojected = np.zeros((src.count, dst_height, dst_width), dtype=source.dtype)
        reproject(source=source, destination=reprojected, src_transform=src.transform, src_crs=src.crs, dst_transform=dst_transform, dst_crs="EPSG:3857")
        left, bottom, right, top = rasterio.transform.array_bounds(dst_height, dst_width, dst_transform)
        lonlat_bounds = transform_bounds("EPSG:3857", "EPSG:4326", left, bottom, right, top, densify_pts=21)
    total_bytes = 0
    total_tiles = 0
    for zoom in range(zoom_min, zoom_max + 1):
        x0, y1 = _tile_xy(lonlat_bounds[0], lonlat_bounds[1], zoom)
        x1, y0 = _tile_xy(lonlat_bounds[2], lonlat_bounds[3], zoom)
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                tile_bounds = transform_bounds("EPSG:4326", "EPSG:3857", *_xyz_bounds_wgs84(x, y, zoom), densify_pts=2)
                tile_transform = from_bounds(*tile_bounds, tile_size, tile_size)
                rendered = np.zeros((source.shape[0], tile_size, tile_size), dtype=np.uint8)
                reproject(source=reprojected, destination=rendered, src_transform=dst_transform, src_crs="EPSG:3857", dst_transform=tile_transform, dst_crs="EPSG:3857")
                rgba = np.zeros((tile_size, tile_size, 4), dtype=np.uint8)
                rgba[..., : min(3, rendered.shape[0])] = np.transpose(rendered[: min(3, rendered.shape[0])], (1, 2, 0))
                if rendered.shape[0] >= 4:
                    rgba[..., 3] = rendered[3]
                else:
                    rgba[..., 3] = np.max(rgba[..., :3], axis=2)
                path = output_dir / str(zoom) / str(x)
                path.mkdir(parents=True, exist_ok=True)
                tile_path = path / f"{y}.png"
                Image.fromarray(rgba, mode="RGBA").save(tile_path, format="PNG")
                total_tiles += 1
                total_bytes += tile_path.stat().st_size
    return {"tile_scheme": "XYZ", "zoom_min": zoom_min, "zoom_max": zoom_max, "bounds_wgs84": lonlat_bounds, "tile_size": tile_size, "tile_count": total_tiles, "tile_bytes": total_bytes, "tile_dir": str(output_dir)}


def build_phase2_manifest(
    geotiff_path: str | Path,
    *,
    dataset: str,
    source: str,
    cog_path: str | Path,
    tile_report: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    raster = build_manifest(geotiff_path, dataset=dataset, source=source, cog_path=cog_path)
    with rasterio.open(geotiff_path) as src:
        bounds_wgs84 = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
    return {
        "run_id": run_id, "dataset": dataset, "source": source,
        "crs": raster.crs, "bounds": raster.bounds, "bounds_wgs84": bounds_wgs84,
        "width": raster.width, "height": raster.height, "pixel_size": [raster.pixel_size_x, raster.pixel_size_y],
        "gsd": raster.pixel_size_x, "geotiff_path": raster.geotiff_path, "cog_path": raster.cog_path,
        "geotiff_bytes": raster.geotiff_bytes, "cog_bytes": raster.cog_bytes, "tiles": tile_report,
        "contract": {"poses": "poses.json", "pair_transforms": "pair_transforms.json", "canvas": "canvas.json"},
    }


def write_phase2_manifest(manifest: dict[str, Any], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return output
