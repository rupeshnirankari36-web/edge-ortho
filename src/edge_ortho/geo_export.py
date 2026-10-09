"""GeoTIFF and COG export primitives for Rupesh's workstream.

All output metadata is derived from the supplied raster and transform. No
project coordinates, dataset names, viewer bounds, tokens, or success values
are hardcoded here.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.shutil import copy as rio_copy
from rasterio.transform import Affine


@dataclass(frozen=True)
class RasterManifest:
    dataset: str
    source: str
    crs: str
    bounds: tuple[float, float, float, float]
    width: int
    height: int
    pixel_size_x: float
    pixel_size_y: float
    count: int
    dtype: str
    nodata: float | int | None
    geotiff_path: str
    cog_path: str | None
    geotiff_bytes: int
    cog_bytes: int | None


def _validate_array(data: np.ndarray) -> np.ndarray:
    array = np.asarray(data)
    if array.ndim not in (2, 3):
        raise ValueError("data must have shape (bands, height, width) or (height, width)")
    if array.ndim == 2:
        array = array[np.newaxis, ...]
    if array.shape[0] not in (1, 3, 4):
        raise ValueError("data must contain 1, 3, or 4 bands")
    if array.shape[1] <= 0 or array.shape[2] <= 0:
        raise ValueError("raster dimensions must be positive")
    return array


def write_geotiff(
    data: np.ndarray,
    path: str | Path,
    *,
    crs: str,
    transform: Affine,
    nodata: float | int | None = 0,
    compress: str = "deflate",
    tiled: bool = True,
    block_size: int = 256,
) -> Path:
    """Write a north-up GeoTIFF and return its path."""
    array = _validate_array(data)
    if not crs:
        raise ValueError("crs is required; refusing an ungeoreferenced raster")
    if transform.a <= 0 or transform.e >= 0:
        raise ValueError("transform must be north-up with positive x and negative y scale")
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    profile: dict[str, Any] = {
        "driver": "GTiff",
        "height": array.shape[1],
        "width": array.shape[2],
        "count": array.shape[0],
        "dtype": array.dtype,
        "crs": crs,
        "transform": transform,
        "nodata": nodata,
        "compress": compress,
        "BIGTIFF": "IF_SAFER",
    }
    if tiled:
        profile.update(tiled=True, blockxsize=block_size, blockysize=block_size)
    with rasterio.open(output, "w", **profile) as dst:
        dst.write(array)
    return output


def convert_to_cog(
    geotiff_path: str | Path,
    cog_path: str | Path,
    *,
    compress: str = "DEFLATE",
    overview_resampling: Resampling = Resampling.average,
) -> Path:
    """Convert a GeoTIFF to a tiled COG with explicit overviews."""
    source = Path(geotiff_path)
    target = Path(cog_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(source, "r+") as src:
        factors = [factor for factor in (2, 4, 8, 16) if min(src.width, src.height) >= factor * 2]
        if not factors:
            raise ValueError("raster is too small to produce a useful overview pyramid")
        src.build_overviews(factors, overview_resampling)
        src.update_tags(ns="rio_overview", resampling=overview_resampling.name)
    with rasterio.open(source) as src:
        rio_copy(
            src,
            target,
            driver="COG",
            compress=compress,
            blocksize=256,
            BIGTIFF="IF_SAFER",
            overview_resampling=overview_resampling.name,
        )
    return target


def build_manifest(
    geotiff_path: str | Path,
    *,
    dataset: str,
    source: str,
    cog_path: str | Path | None = None,
) -> RasterManifest:
    """Read actual raster metadata and write no assumptions into the result."""
    tif = Path(geotiff_path)
    cog = Path(cog_path) if cog_path else None
    with rasterio.open(tif) as src:
        bounds = (src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top)
        manifest = RasterManifest(
            dataset=dataset,
            source=source,
            crs=src.crs.to_string() if src.crs else "",
            bounds=bounds,
            width=src.width,
            height=src.height,
            pixel_size_x=src.transform.a,
            pixel_size_y=abs(src.transform.e),
            count=src.count,
            dtype=src.dtypes[0],
            nodata=src.nodata,
            geotiff_path=str(tif),
            cog_path=str(cog) if cog else None,
            geotiff_bytes=tif.stat().st_size,
            cog_bytes=cog.stat().st_size if cog and cog.exists() else None,
        )
    if not manifest.crs:
        raise ValueError("raster has no CRS")
    if manifest.pixel_size_x <= 0 or manifest.pixel_size_y <= 0:
        raise ValueError("raster pixel size must be positive")
    return manifest


def write_manifest(manifest: RasterManifest, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(manifest), indent=2) + "\n", encoding="utf-8")
    return output
