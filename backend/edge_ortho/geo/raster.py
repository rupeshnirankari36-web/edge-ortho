"""Geospatial output: GeoTIFF, COG conversion and XYZ web tiles.

The brief is explicit that georeferencing must not be asserted without support:

    "Generate a georeferenced GeoTIFF only when the output placement and CRS
    are sufficiently supported by the available metadata and transforms."
    "Validate output dimensions, CRS, affine transform, bounds, and readability."
    "Add COG conversion and XYZ tiles only if the required tooling is available."

So every capability is probed at runtime and reported. When a tool is missing
the run says *why* the artifact is absent instead of silently omitting it.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rasterio.transform import from_origin

try:
    import rasterio
    from rasterio.crs import CRS
    from rasterio.enums import Resampling
    from rasterio.warp import reproject as warp_reproject
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window

    RASTERIO_AVAILABLE = True
    RASTERIO_ERROR = None
except Exception as exc:  # pragma: no cover - environment dependent
    RASTERIO_AVAILABLE = False
    RASTERIO_ERROR = str(exc)

WEB_MERCATOR = "EPSG:3857"
TILE_PX = 256
MAX_XYZ_TILES = 4000


def capabilities() -> dict:
    """Report which geospatial tooling this machine actually provides."""
    caps: dict = {
        "rasterio": RASTERIO_AVAILABLE,
        "rasterio_error": RASTERIO_ERROR,
        "rio_cogeo_cli": bool(shutil.which("rio")),
        "gdalinfo": bool(shutil.which("gdalinfo")),
        "gdal_translate": bool(shutil.which("gdal_translate")),
        "gdaladdo": bool(shutil.which("gdaladdo")),
        "gdal2tiles": bool(shutil.which("gdal2tiles")),
        "cog_driver": False,
        "drivers": [],
    }
    if RASTERIO_AVAILABLE:
        try:
            with rasterio.Env() as env:
                drivers = sorted(env.drivers().keys())
            caps["drivers"] = drivers
            caps["cog_driver"] = "COG" in drivers
        except Exception as exc:  # pragma: no cover
            caps["driver_error"] = str(exc)
    return caps


@dataclass
class RasterWriteResult:
    path: str | None
    bytes: int | None
    width: int
    height: int
    bands: int
    crs: str | None
    transform: list[float] | None
    bounds: list[float] | None
    bounds_wgs84: list[float] | None
    nodata: float | None
    messages: list[str]
    validation: dict


def write_geotiff_from_tiles(
    tiles: dict[tuple[int, int], np.ndarray],
    out_path: str | Path,
    tile_grid_size: int,
    width: int,
    height: int,
    gsd_m: float,
    origin_e: float,
    origin_n: float,
    crs_epsg: int | None,
    nodata: int | None = 0,
) -> RasterWriteResult:
    """Write the composed tiles into a tiled, compressed GeoTIFF.

    Tiles are streamed one at a time through a rasterio windowed write, so the
    full canvas never exists in memory.
    """
    out_path = Path(out_path)
    messages: list[str] = []
    if not RASTERIO_AVAILABLE:
        return RasterWriteResult(
            None, None, width, height, 0, None, None, None, None, None,
            [f"rasterio unavailable: {RASTERIO_ERROR}"], {"readable": False},
        )

    crs = CRS.from_epsg(crs_epsg) if crs_epsg else None
    transform = from_origin(origin_e, origin_n, gsd_m, gsd_m)

    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 4,
        "dtype": "uint8",
        "crs": crs,
        "transform": transform,
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "compress": "deflate",
        "predictor": 2,
        "interleave": "pixel",
    }
    if nodata is not None:
        profile["nodata"] = nodata
        messages.append("Band 4 is an alpha mask; nodata=0 marks never-covered pixels.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        for (tx, ty), rgba in sorted(tiles.items()):
            col_off, row_off = tx * tile_grid_size, ty * tile_grid_size
            h, w = rgba.shape[:2]
            if col_off >= width or row_off >= height:
                continue
            w = min(w, width - col_off)
            h = min(h, height - row_off)
            for band in range(4):
                dst.write(rgba[:h, :w, band], band + 1, window=Window(col_off, row_off, w, h))

    return validate_raster(out_path, messages)


class GeoTiffWriter:
    """Streams composed tiles straight into a tiled GeoTIFF.

    Used as a context manager. Only one windowed block is in flight at a time, so
    the full canvas is never materialised.
    """

    #: GDAL's block cache defaults to a few hundred MB, which would dominate the
    #: memory profile of a constrained run. It is capped explicitly so the
    #: measured peak RSS reflects the pipeline rather than the driver default.
    DEFAULT_CACHE_MB = 128

    def __init__(
        self,
        path: str | Path,
        width: int,
        height: int,
        gsd_m: float,
        origin_e: float,
        origin_n: float,
        crs_epsg: int | None,
        nodata: int | None = 0,
        cache_mb: int | None = None,
    ):
        self.path = Path(path)
        self.width = width
        self.height = height
        self.messages: list[str] = []
        self.tiles_written = 0
        self._ds = None
        self._crs = None
        self._env = None
        self._transform = from_origin(origin_e, origin_n, gsd_m, gsd_m)
        self._nodata = nodata
        self._crs_epsg = crs_epsg
        self._cache_mb = self.DEFAULT_CACHE_MB if cache_mb is None else cache_mb
        if crs_epsg:
            self._crs = CRS.from_epsg(crs_epsg)

    def __enter__(self) -> GeoTiffWriter:
        if not RASTERIO_AVAILABLE:
            self.messages.append(f"rasterio unavailable: {RASTERIO_ERROR}")
            return self
        self._env = rasterio.Env(GDAL_CACHEMAX=self._cache_mb)
        self._env.__enter__()
        profile = {
            "driver": "GTiff",
            "height": self.height,
            "width": self.width,
            "count": 4,
            "dtype": "uint8",
            "crs": self._crs,
            "transform": self._transform,
            "tiled": True,
            "blockxsize": 512,
            "blockysize": 512,
            "compress": "deflate",
            "predictor": 2,
            "interleave": "pixel",
        }
        if self._nodata is not None:
            profile["nodata"] = self._nodata
            self.messages.append(
                "Band 4 is a composited alpha mask; nodata=0 marks pixels no frame covered."
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ds = rasterio.open(self.path, "w", **profile)
        return self

    def write_tile(self, tx: int, ty: int, rgba: np.ndarray, tile_grid_size: int) -> None:
        if self._ds is None:
            return
        col_off, row_off = tx * tile_grid_size, ty * tile_grid_size
        if col_off >= self.width or row_off >= self.height:
            return
        h, w = rgba.shape[:2]
        w = min(w, self.width - col_off)
        h = min(h, self.height - row_off)
        for band in range(4):
            self._ds.write(rgba[:h, :w, band], band + 1, window=Window(col_off, row_off, w, h))
        self.tiles_written += 1

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._ds is not None:
            self._ds.close()
            self._ds = None
        if self._env is not None:
            self._env.__exit__(exc_type, exc, tb)
            self._env = None
        return False

    def result(self) -> RasterWriteResult:
        if not self.path.exists():
            return RasterWriteResult(
                None, None, self.width, self.height, 0, None, None, None, None, None,
                self.messages, {"readable": False, "checked": []},
            )
        return validate_raster(self.path, self.messages)


class PreviewAccumulator:
    """Builds a bounded downscaled preview as tiles stream past.

    The accumulation buffer is capped at ``max_side`` so its cost is constant
    regardless of the output canvas size.
    """

    def __init__(self, width: int, height: int, max_side: int = 4096):
        scale = min(1.0, max_side / max(1, max(width, height)))
        self.scale = scale
        self.width = max(1, round(width * scale))
        self.height = max(1, round(height * scale))
        self.acc = np.zeros((self.height, self.width, 3), dtype=np.float32)
        self.alpha = np.zeros((self.height, self.width), dtype=np.float32)

    def add(self, tx: int, ty: int, rgba: np.ndarray, tile_grid_size: int) -> None:
        import cv2

        x0 = round(tx * tile_grid_size * self.scale)
        y0 = round(ty * tile_grid_size * self.scale)
        if x0 >= self.width or y0 >= self.height:
            return
        tw = min(round(rgba.shape[1] * self.scale), self.width - x0)
        th = min(round(rgba.shape[0] * self.scale), self.height - y0)
        if tw <= 0 or th <= 0:
            return
        small = cv2.resize(rgba, (tw, th), interpolation=cv2.INTER_AREA)
        a = small[:, :, 3].astype(np.float32) / 255.0
        self.acc[y0 : y0 + th, x0 : x0 + tw] += small[:, :, :3].astype(np.float32) * a[:, :, None]
        self.alpha[y0 : y0 + th, x0 : x0 + tw] += a

    def save(self, out_path: str | Path) -> dict:
        import cv2

        out_path = Path(out_path)
        safe = np.maximum(self.alpha, 1e-6)[:, :, None]
        rgb = np.clip(self.acc / safe, 0, 255).astype(np.uint8)
        # The GeoTIFF retains its alpha mask, but a browser-facing photo view
        # should not present transparent no-data pixels as a black void.
        rgb[self.alpha <= 1e-6] = 255
        out_path.parent.mkdir(parents=True, exist_ok=True)
        ok, buf = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        if not ok:
            return {"produced": False, "messages": ["PNG encode failed"]}
        out_path.write_bytes(buf.tobytes())
        return {
            "produced": True,
            "path": str(out_path),
            "bytes": out_path.stat().st_size,
            "width": self.width,
            "height": self.height,
            "scale": self.scale,
            "buffer_mb": (self.acc.nbytes + self.alpha.nbytes) / (1024 * 1024),
        }


def validate_raster(path: str | Path, messages: list[str] | None = None) -> RasterWriteResult:
    """Reopen a raster and check the properties the brief requires."""
    path = Path(path)
    messages = list(messages or [])
    validation: dict = {"readable": False, "checked": []}
    if not RASTERIO_AVAILABLE:
        return RasterWriteResult(
            None, None, 0, 0, 0, None, None, None, None, None,
            [f"rasterio unavailable: {RASTERIO_ERROR}"], validation,
        )
    try:
        with rasterio.open(path) as src:
            validation["readable"] = True
            validation["checked"].append("open")
            validation["driver"] = src.driver
            validation["count"] = src.count
            validation["dtype"] = src.dtypes[0]
            validation["is_tiled"] = bool(src.profile.get("tiled"))
            validation["block_shapes"] = [list(b) for b in src.block_shapes]
            validation["overviews"] = src.overviews(1)

            # force an actual pixel read, not just a header read
            sample_h = min(64, src.height)
            sample_w = min(64, src.width)
            window = Window(
                max(0, (src.width - sample_w) // 2), max(0, (src.height - sample_h) // 2),
                sample_w, sample_h,
            )
            arr = src.read(1, window=window)
            validation["centre_sample_nonzero"] = int(arr.max()) > 0
            validation["checked"].append("read_window")

            crs_ok = src.crs is not None
            validation["crs_present"] = crs_ok
            if not crs_ok:
                messages.append("Raster has no CRS: this is a visual mosaic, not a georeferenced one.")
            transform = src.transform
            validation["transform"] = list(transform)[:6]
            validation["transform_is_affine_northup"] = (
                abs(transform.b) < 1e-9 and abs(transform.d) < 1e-9
            )
            validation["pixel_size"] = [abs(transform.a), abs(transform.e)]
            validation["bounds"] = [src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top]
            bounds_wgs84 = None
            if crs_ok:
                try:
                    bounds_wgs84 = list(transform_bounds(src.crs, "EPSG:4326", *src.bounds))
                except Exception as exc:  # pragma: no cover
                    messages.append(f"could not reproject bounds to WGS84: {exc}")
            validation["bounds_wgs84"] = bounds_wgs84
            return RasterWriteResult(
                path=str(path),
                bytes=path.stat().st_size,
                width=src.width,
                height=src.height,
                bands=src.count,
                crs=src.crs.to_string() if src.crs else None,
                transform=list(transform)[:6],
                bounds=validation["bounds"],
                bounds_wgs84=bounds_wgs84,
                nodata=src.nodata,
                messages=messages,
                validation=validation,
            )
    except Exception as exc:
        validation["error"] = str(exc)
        messages.append(f"raster validation failed: {exc}")
        return RasterWriteResult(
            None, None, 0, 0, 0, None, None, None, None, None, messages, validation
        )


def convert_to_cog(src_path: str | Path, dst_path: str | Path) -> dict:
    """Convert a GeoTIFF to Cloud Optimized GeoTIFF.

    Tries, in order: the ``rio cogeo`` CLI, GDAL's COG driver, then documented
    failure. Never claims success without reopening the result.
    """
    src_path, dst_path = Path(src_path), Path(dst_path)
    result: dict = {"produced": False, "driver": None, "path": None, "bytes": None, "messages": []}
    if not src_path.exists():
        result["messages"].append("source GeoTIFF does not exist")
        return result

    rio = shutil.which("rio")
    if rio:
        try:
            proc = subprocess.run(
                [rio, "cogeo", "create", str(src_path), str(dst_path), "--overview-resampling", "nearest"],
                capture_output=True,
                text=True,
                timeout=900,
            )
            if proc.returncode == 0 and dst_path.exists():
                result.update(
                    produced=True, driver="rio-cogeo", path=str(dst_path), bytes=dst_path.stat().st_size
                )
                result["messages"].append("created with the rio-cogeo CLI")
                return result
            result["messages"].append(
                f"rio cogeo exited {proc.returncode}: {(proc.stderr or '').strip()[:300]}"
            )
        except Exception as exc:
            result["messages"].append(f"rio cogeo failed: {exc}")

    caps = capabilities()
    if caps.get("cog_driver") and RASTERIO_AVAILABLE:
        # Prefer a compact web COG: JPEG-compressed RGB plus a GDAL internal mask.
        # A lossless RGBA COG is several times larger for no web benefit, and the
        # mask keeps the covered footprint honest. Falls back to deflate RGBA.
        for mode in ("jpeg_mask", "deflate_rgba"):
            try:
                _write_cog(src_path, dst_path, mode)
                check = validate_raster(dst_path)
                if not (check.width and dst_path.exists()):
                    result["messages"].append(f"COG ({mode}) failed reopen validation")
                    continue
                has_mask = False
                with rasterio.open(dst_path) as ds:
                    has_mask = bool(ds.mask_flag_enums and any(ds.mask_flag_enums))
                result.update(
                    produced=True,
                    driver=f"GDAL COG driver ({mode})",
                    path=str(dst_path),
                    bytes=dst_path.stat().st_size,
                )
                result["messages"].append(
                    f"created with GDAL's COG driver ({mode}), reopened successfully; "
                    f"internal mask present: {has_mask}"
                )
                result["validation"] = check.validation
                result["has_internal_mask"] = has_mask
                result["mode"] = mode
                return result
            except Exception as exc:
                result["messages"].append(f"GDAL COG driver ({mode}) failed: {exc}")

    if not rio:
        result["messages"].append("rio-cogeo CLI not installed (pip install rio-cogeo)")
    if not caps.get("cog_driver"):
        result["messages"].append("GDAL COG driver not available in this rasterio build")
    result["messages"].append("COG conversion unavailable; the plain GeoTIFF remains valid and readable.")
    return result


def _write_cog(src_path: Path, dst_path: Path, mode: str) -> None:
    """Write one COG variant with the GDAL COG driver.

    ``jpeg_mask`` keeps only the RGB bands and moves the alpha band into a GDAL
    internal mask, which is what makes JPEG (and therefore a small file)
    possible. ``deflate_rgba`` keeps all four bands losslessly.

    The source is copied strip by strip rather than with ``src.read()``: reading
    the whole raster first would allocate width x height x bands bytes (240 MB for
    a 60 MP four-band mosaic) for no benefit, since GDAL encodes one 512 x 512
    block at a time either way.
    """
    if dst_path.exists():
        dst_path.unlink()
    strip_rows = 512
    with rasterio.open(src_path) as src:
        profile = src.profile.copy()
        for key in ("blockxsize", "blockysize", "tiled", "interleave", "predictor", "nodata"):
            profile.pop(key, None)
        profile.update(driver="COG", blocksize=512, overview_resampling="average")
        if mode == "jpeg_mask":
            profile.update(count=3, compress="JPEG", photometric="YCBCR", quality=88)
        else:
            profile.update(count=4, compress="DEFLATE")

        bands = 3 if mode == "jpeg_mask" else min(4, src.count)
        with_mask = mode == "jpeg_mask" and src.count >= 4

        # GDAL's block cache defaults to a share of total system memory, and building
        # the overview pyramid on a mosaic easily pushes that to hundreds of megabytes.
        # The ceiling is set explicitly here for the same reason the tile writer sets
        # it: the measured peak RSS must describe the pipeline, not the driver default.
        with rasterio.Env(GDAL_CACHEMAX=COG_CACHE_MB), rasterio.open(dst_path, "w", **profile) as dst:
                for row in range(0, src.height, strip_rows):
                    rows = min(strip_rows, src.height - row)
                    window = Window(0, row, src.width, rows)
                    dst.write(src.read(list(range(1, bands + 1)), window=window), window=window)
                    if with_mask:
                        dst.write_mask(src.read(4, window=window), window=window)
                _build_overviews(dst)


def _build_overviews(dst) -> None:
    try:
        factors = [f for f in (2, 4, 8, 16) if f < max(dst.width, dst.height)]
        if factors:
            dst.build_overviews(factors, Resampling.average)
            dst.update_tags(ns="rio_overview", resampling="average")
    except Exception:
        pass


#: GDAL block cache ceiling while writing a COG and its overviews, in MB.
COG_CACHE_MB = 128


# ---------------------------------------------------------------------------
# XYZ web tiles
# ---------------------------------------------------------------------------


def _lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[float, float]:
    n = 2.0**z
    x = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(max(-85.05112878, min(85.05112878, lat)))
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def choose_zoom_range(
    gsd_m: float,
    bounds_wgs84: list[float] | None,
    max_zoom: int = 19,
) -> tuple[int, int]:
    """Pick min/max web zoom levels that match the mosaic's real resolution."""
    # Web Mercator ground resolution at the equator: 156543.03 / 2^z m/px, scaled
    # by cos(latitude). Using the mosaic's own latitude keeps the zoom levels
    # representative of the ground, not of the equator.
    lat = 0.0
    if bounds_wgs84:
        lat = 0.5 * (bounds_wgs84[1] + bounds_wgs84[3])
    if gsd_m and gsd_m > 0:
        resolution_at_equator = gsd_m * max(0.05, math.cos(math.radians(lat)))
        z_native = round(math.log2(156543.03392 / resolution_at_equator))
        z_native = max(0, min(max_zoom, z_native))
    else:
        z_native = 0
    min_zoom = max(0, z_native - 4)
    if bounds_wgs84:
        # Do not go below the zoom where the whole mosaic is smaller than one tile.
        span = max(bounds_wgs84[2] - bounds_wgs84[0], bounds_wgs84[3] - bounds_wgs84[1])
        if span > 0:
            z_fit = math.floor(math.log2(360.0 / max(span, 1e-9))) - 1
            min_zoom = max(min_zoom, max(0, min(z_fit, z_native)))
    return min_zoom, z_native


def generate_xyz_tiles(
    raster_path: str | Path,
    out_dir: str | Path,
    min_zoom: int,
    max_zoom: int,
) -> dict:
    """Render XYZ PNG tiles from a GeoTIFF.

    A pure rasterio/GDAL implementation (no gdal2tiles process), reading one
    tile-sized window at a time so memory stays bounded. Returns a manifest with
    the real tile count, zooms and any limitation encountered.
    """
    raster_path, out_dir = Path(raster_path), Path(out_dir)
    info: dict = {
        "produced": False,
        "tile_count": 0,
        "min_zoom": None,
        "max_zoom": None,
        "dir": None,
        "messages": [],
    }
    if not RASTERIO_AVAILABLE:
        info["messages"].append("rasterio unavailable: cannot generate XYZ tiles")
        return info
    if not raster_path.exists():
        info["messages"].append("GeoTIFF missing")
        return info

    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    tiles_per_zoom: dict[str, int] = {}
    try:
        with rasterio.open(raster_path) as src:
            if src.crs is None:
                info["messages"].append("raster has no CRS: web tiles would not be placed correctly")
                return info
            bounds_ll = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
            for z in range(min_zoom, max_zoom + 1):
                x0f, y0f = _lonlat_to_tile(bounds_ll[0], bounds_ll[3], z)
                x1f, y1f = _lonlat_to_tile(bounds_ll[2], bounds_ll[1], z)
                tx0, tx1 = math.floor(x0f), math.floor(x1f)
                ty0, ty1 = math.floor(y0f), math.floor(y1f)
                n = 2**z
                tx0, tx1 = max(0, tx0), min(n - 1, tx1)
                ty0, ty1 = max(0, ty0), min(n - 1, ty1)
                if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) * max(1, count) > MAX_XYZ_TILES:
                    info["messages"].append(
                        f"stopped at zoom {z}: tile budget of {MAX_XYZ_TILES} reached"
                    )
                    break
                written = 0
                for tx in range(tx0, tx1 + 1):
                    for ty in range(ty0, ty1 + 1):
                        if count >= MAX_XYZ_TILES:
                            break
                        png = _render_tile(src, z, tx, ty)
                        if png is None:
                            continue
                        d = out_dir / str(z) / str(tx)
                        d.mkdir(parents=True, exist_ok=True)
                        (d / f"{ty}.png").write_bytes(png)
                        count += 1
                        written += 1
                tiles_per_zoom[str(z)] = written
                if count >= MAX_XYZ_TILES:
                    break
    except Exception as exc:
        info["messages"].append(f"tile generation failed: {exc}")
        if count == 0:
            return info

    if count == 0:
        info["messages"].append("no tiles were produced")
        if _TILE_ERRORS:
            info["messages"].extend(f"warp error: {e}" for e in _TILE_ERRORS[-3:])
        return info
    info.update(
        produced=True,
        tile_count=count,
        min_zoom=min_zoom,
        max_zoom=max_zoom,
        dir=str(out_dir),
        tiles_per_zoom=tiles_per_zoom,
    )
    return info


def _render_tile(src, z: int, tx: int, ty: int) -> bytes | None:
    """Reproject and rasterise exactly one XYZ tile into PNG bytes."""
    import cv2

    n = 2.0**z
    lon0 = tx / n * 360.0 - 180.0
    lon1 = (tx + 1) / n * 360.0 - 180.0

    def lat_of(y: float) -> float:
        t = math.pi * (1.0 - 2.0 * y / n)
        return math.degrees(math.atan(math.sinh(t)))

    lat1 = lat_of(ty)
    lat0 = lat_of(ty + 1)

    # rasterio expects ndarray destinations in (bands, rows, cols) order.
    bands = min(4, src.count)
    dst = np.zeros((bands, TILE_PX, TILE_PX), dtype=np.uint8)
    try:
        warp_reproject(
            source=rasterio.band(src, list(range(1, bands + 1))),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=from_origin(tx / n * 40075016.686 - 20037508.343,
                                      -ty / n * 40075016.686 + 20037508.343,
                                      40075016.686 / (n * TILE_PX),
                                      40075016.686 / (n * TILE_PX)),
            dst_crs=WEB_MERCATOR,
            dst_nodata=0,
            resampling=Resampling.bilinear,
            num_threads=1,
        )
    except Exception as exc:
        _TILE_ERRORS.append(str(exc))
        return None
    _ = (lon0, lon1, lat0, lat1)
    if not dst.any():
        return None
    rgba = np.transpose(dst, (1, 2, 0))
    if rgba.shape[2] == 3:
        alpha = np.where(rgba.any(axis=2), 255, 0).astype(np.uint8)
        rgba = np.dstack([rgba, alpha])
    if not rgba[:, :, 3].any():
        return None
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    return buf.tobytes() if ok else None


#: Last few warp errors, surfaced so a silent empty tile set cannot hide a bug.
_TILE_ERRORS: list[str] = []


def write_preview_png(
    tiles: dict[tuple[int, int], np.ndarray],
    out_path: str | Path,
    tile_grid_size: int,
    width: int,
    height: int,
    max_side: int = 1600,
) -> dict:
    """Stitch the composed tiles into one downscaled preview PNG for the UI."""
    import cv2

    out_path = Path(out_path)
    if not tiles:
        return {"produced": False, "messages": ["no tiles to preview"]}

    scale = min(1.0, max_side / max(width, height))
    pw, ph = max(1, int(width * scale)), max(1, int(height * scale))
    canvas = np.zeros((ph, pw, 4), dtype=np.uint8)
    for (tx, ty), rgba in tiles.items():
        x0 = int(tx * tile_grid_size * scale)
        y0 = int(ty * tile_grid_size * scale)
        if x0 >= pw or y0 >= ph:
            continue
        tw = min(int(rgba.shape[1] * scale), pw - x0)
        th = min(int(rgba.shape[0] * scale), ph - y0)
        if tw <= 0 or th <= 0:
            continue
        small = cv2.resize(rgba, (tw, th), interpolation=cv2.INTER_AREA)
        region = canvas[y0 : y0 + th, x0 : x0 + tw]
        a = small[:, :, 3:4].astype(np.float32) / 255.0
        region[:, :, :3] = (small[:, :, :3].astype(np.float32) * a).astype(np.uint8)
        region[:, :, 3] = small[:, :, 3]

    flat = np.zeros((ph, pw, 3), dtype=np.uint8)
    alpha = canvas[:, :, 3:4].astype(np.float32) / 255.0
    flat[:] = (canvas[:, :, :3].astype(np.float32) / np.maximum(alpha, 1e-6)).clip(0, 255)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", cv2.cvtColor(flat, cv2.COLOR_RGB2BGR))
    if not ok:
        return {"produced": False, "messages": ["PNG encode failed"]}
    out_path.write_bytes(buf.tobytes())
    return {
        "produced": True,
        "path": str(out_path),
        "bytes": out_path.stat().st_size,
        "width": pw,
        "height": ph,
        "scale": scale,
    }
