"""XYZ raster tile generator for Leaflet and Mapbox GL JS web maps."""

import json
import math
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import Resampling, calculate_default_transform, reproject


def _deg2num(lat_deg: float, lon_deg: float, zoom: int) -> tuple[int, int]:
    """Converts WGS84 lat/lon to Slippy map tile X, Y coordinates at given zoom level."""
    lat_rad = math.radians(lat_deg)
    n = 2.0**zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile


def _num2deg(xtile: int, ytile: int, zoom: int) -> tuple[float, float, float, float]:
    """Returns WGS84 bounding box (min_lon, min_lat, max_lon, max_lat) of a tile."""
    n = 2.0**zoom
    lon_min = xtile / n * 360.0 - 180.0
    lon_max = (xtile + 1) / n * 360.0 - 180.0
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ytile / n))))
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ytile + 1) / n))))
    return lon_min, lat_min, lon_max, lat_max


def generate_xyz_tiles(
    geotiff_path: Path,
    output_tiles_dir: Path,
    bounds_wgs84: tuple[float, float, float, float],
    min_zoom: int | None = None,
    max_zoom: int | None = None,
) -> int:
    """
    Generates standard XYZ raster tiles (z/x/y.png) in EPSG:3857 Web Mercator
    for interactive web viewing in Leaflet and Mapbox GL JS.
    Returns total tiles generated.
    """
    output_tiles_dir.mkdir(parents=True, exist_ok=True)
    min_lon, min_lat, max_lon, max_lat = bounds_wgs84

    # Reproject or read source dataset into EPSG:3857 Web Mercator
    with rasterio.open(geotiff_path) as src:
        # Determine natural zoom level from GSD
        # At zoom 18, 1 pixel is ~0.60 m; at zoom 19, ~0.30 m; at zoom 20, ~0.15 m
        transform_3857, w_3857, h_3857 = calculate_default_transform(
            src.crs, "EPSG:3857", src.width, src.height, *src.bounds
        )

        res_m = abs(transform_3857.a)
        natural_zoom = int(round(math.log2(156543.03392 / max(res_m, 0.05))))
        natural_zoom = max(14, min(19, natural_zoom))

        if min_zoom is None:
            min_zoom = max(14, natural_zoom - 1)
        if max_zoom is None:
            max_zoom = max(min_zoom, min(19, natural_zoom))

        # Reproject to memory 3857 array
        warped_data = np.zeros((4, h_3857, w_3857), dtype=np.uint8)
        reproject(
            source=rasterio.band(src, [1, 2, 3, 4]),
            destination=warped_data,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=transform_3857,
            dst_crs="EPSG:3857",
            resampling=Resampling.bilinear,
        )

    # Invert 3857 transform to map world coordinates to warped_data pixels
    inv_transform = ~transform_3857
    total_tiles_generated = 0

    for z in range(min_zoom, max_zoom + 1):
        x_min, y_min = _deg2num(max_lat, min_lon, z)
        x_max, y_max = _deg2num(min_lat, max_lon, z)

        # Ensure order
        x_start, x_end = min(x_min, x_max), max(x_min, x_max)
        y_start, y_end = min(y_min, y_max), max(y_min, y_max)

        for x in range(x_start, x_end + 1):
            for y in range(y_start, y_end + 1):
                t_lon_min, t_lat_min, t_lon_max, t_lat_max = _num2deg(x, y, z)

                # Convert tile WGS84 corners to 3857 coordinates
                # Mercator formulas:
                def _to_3857(lon, lat):
                    mx = lon * 20037508.34 / 180.0
                    my = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
                    my = my * 20037508.34 / 180.0
                    return mx, my

                mx_min, my_max = _to_3857(t_lon_min, t_lat_max)
                mx_max, my_min = _to_3857(t_lon_max, t_lat_min)

                px0, py0 = inv_transform @ (mx_min, my_max)
                px1, py1 = inv_transform @ (mx_max, my_min)

                col0, col1 = int(round(min(px0, px1))), int(round(max(px0, px1)))
                row0, row1 = int(round(min(py0, py1))), int(round(max(py0, py1)))

                if col1 < 0 or col0 >= w_3857 or row1 < 0 or row0 >= h_3857:
                    continue

                c_clamped0, c_clamped1 = max(0, col0), min(w_3857, col1)
                r_clamped0, r_clamped1 = max(0, row0), min(h_3857, row1)

                if c_clamped1 <= c_clamped0 or r_clamped1 <= r_clamped0:
                    continue

                patch = warped_data[:, r_clamped0:r_clamped1, c_clamped0:c_clamped1]
                # Check if patch has visible pixels (alpha > 0)
                if not np.any(patch[3] > 0):
                    continue

                # Create 256x256 RGBA tile
                tile_rgba = np.zeros((4, 256, 256), dtype=np.uint8)
                # Compute scaling into 256x256
                tw_span = col1 - col0
                th_span = row1 - row0
                if tw_span <= 0 or th_span <= 0:
                    continue

                dx0 = int(round(256 * (c_clamped0 - col0) / tw_span))
                dx1 = int(round(256 * (c_clamped1 - col0) / tw_span))
                dy0 = int(round(256 * (r_clamped0 - row0) / th_span))
                dy1 = int(round(256 * (r_clamped1 - row0) / th_span))

                dx0, dx1 = max(0, min(256, dx0)), max(0, min(256, dx1))
                dy0, dy1 = max(0, min(256, dy0)), max(0, min(256, dy1))

                if dx1 > dx0 and dy1 > dy0:
                    # Resize patch to fit tile window
                    patch_trans = np.transpose(patch, (1, 2, 0))  # H, W, 4
                    resized = Image.fromarray(patch_trans).resize(
                        (dx1 - dx0, dy1 - dy0), Image.BILINEAR
                    )
                    tile_rgba[:, dy0:dy1, dx0:dx1] = np.transpose(np.array(resized), (2, 0, 1))

                # Save tile as PNG
                tile_dir = output_tiles_dir / str(z) / str(x)
                tile_dir.mkdir(parents=True, exist_ok=True)
                tile_path = tile_dir / f"{y}.png"

                tile_img = Image.fromarray(np.transpose(tile_rgba, (1, 2, 0)), mode="RGBA")
                tile_img.save(tile_path, format="PNG", optimize=True)
                total_tiles_generated += 1

    # Write tile metadata tilejson.json
    metadata = {
        "tilejson": "2.2.0",
        "name": "edge-ortho-mosaic",
        "format": "png",
        "minzoom": min_zoom,
        "maxzoom": max_zoom,
        "bounds": list(bounds_wgs84),
        "center": [(min_lon + max_lon) / 2.0, (min_lat + max_lat) / 2.0, min_zoom],
        "tiles": ["{z}/{x}/{y}.png"],
    }
    with open(output_tiles_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    return total_tiles_generated
