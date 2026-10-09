"""Georeferenced GeoTIFF creation with chunked window streaming."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyproj
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window

from ..compose.tiling import CanvasLayout, TileResult
from ..ingest.models import FrameRecord


@dataclass
class GeoTIFFMetadata:
    output_path: Path
    crs_epsg: int
    transform: list[float]  # 6-element affine tuple
    bounds_utm: tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)
    bounds_wgs84: tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat)
    width: int
    height: int
    pixel_size_m: float
    filesize_bytes: int


def calculate_georeference_transform(
    records: Sequence[FrameRecord],
    layout: CanvasLayout,
    gsd_m: float,
    epsg_code: int,
) -> tuple[rasterio.Affine, tuple[float, float, float, float], tuple[float, float, float, float]]:
    """Calculates rasterio Affine transform and bounding boxes in UTM and WGS84."""
    eastings = [r.utm_easting for r in records if r.utm_easting is not None]
    northings = [r.utm_northing for r in records if r.utm_northing is not None]

    base_min_e = min(eastings)
    base_max_n = max(northings)

    # In layout, min_x and min_y are relative canvas offsets
    origin_e = base_min_e + layout.min_x * gsd_m
    origin_n = base_max_n - layout.min_y * gsd_m

    transform = from_origin(origin_e, origin_n, gsd_m, gsd_m)

    max_e = origin_e + layout.width_px * gsd_m
    min_n = origin_n - layout.height_px * gsd_m

    bounds_utm = (origin_e, min_n, max_e, origin_n)

    # Convert bounds to WGS84 for web viewers
    try:
        transformer = pyproj.Transformer.from_crs(f"EPSG:{epsg_code}", "EPSG:4326", always_xy=True)
        wgs_min_lon, wgs_min_lat = transformer.transform(origin_e, min_n)
        wgs_max_lon, wgs_max_lat = transformer.transform(max_e, origin_n)
        bounds_wgs84 = (wgs_min_lon, wgs_min_lat, wgs_max_lon, wgs_max_lat)
    except Exception:
        bounds_wgs84 = (0.0, 0.0, 0.0, 0.0)

    return transform, bounds_utm, bounds_wgs84


def create_empty_geotiff(
    output_path: Path,
    width: int,
    height: int,
    transform: rasterio.Affine,
    epsg_code: int,
    bands: int = 4,  # RGBA
) -> rasterio.io.DatasetWriter:
    """Initializes a georeferenced GeoTIFF container with tiled internal layout for streaming writes."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": bands,
        "dtype": "uint8",
        "crs": rasterio.crs.CRS.from_epsg(epsg_code),
        "transform": transform,
        "nodata": 0,
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "compress": "deflate",
        "predictor": 2,
    }

    return rasterio.open(output_path, "w", **profile)


def write_tile_to_geotiff(
    dataset: rasterio.io.DatasetWriter,
    tile: TileResult,
) -> None:
    """Streams a processed TileResult into the open rasterio dataset window."""
    x0, y0, x1, y1 = tile.bounds_px
    tw = x1 - x0
    th = y1 - y0

    window = Window(x0, y0, tw, th)

    if tile.is_empty:
        # Fill window with zeros
        empty_data = np.zeros((4, th, tw), dtype=np.uint8)
        dataset.write(empty_data, window=window)
        return

    # tile.rgb is BGR uint8 from OpenCV
    # Convert BGR to RGB
    r_chan = tile.rgb[:, :, 2]
    g_chan = tile.rgb[:, :, 1]
    b_chan = tile.rgb[:, :, 0]
    a_chan = tile.alpha

    rgba_stack = np.stack([r_chan, g_chan, b_chan, a_chan], axis=0)
    dataset.write(rgba_stack, window=window)
