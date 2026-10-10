"""Coordinate reference system helpers.

The brief requires GPS to be converted into "a projected coordinate system such
as UTM" before any neighbour planning or canvas work. All canvas arithmetic in
EdgeOrtho is therefore done in metres on a UTM grid; this keeps the output
raster north-up with a plain affine transform.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyproj import CRS, Transformer

WGS84_EPSG = 4326


def utm_epsg(lon: float, lat: float) -> int:
    """Return the EPSG code of the WGS84 UTM zone containing (lon, lat)."""
    zone = int((lon + 180.0) // 6.0) + 1
    zone = max(1, min(60, zone))
    if lat >= 0:
        return 32600 + zone
    return 32700 + zone


@dataclass
class Projector:
    """Forward/inverse transforms between WGS84 and one projected CRS."""

    epsg: int
    _fwd: Transformer
    _inv: Transformer

    @classmethod
    def for_points(cls, lon: float, lat: float) -> Projector:
        epsg = utm_epsg(lon, lat)
        return cls.for_epsg(epsg)

    @classmethod
    def for_epsg(cls, epsg: int) -> Projector:
        target = CRS.from_epsg(epsg)
        return cls(
            epsg=epsg,
            _fwd=Transformer.from_crs(WGS84_EPSG, target, always_xy=True),
            _inv=Transformer.from_crs(target, WGS84_EPSG, always_xy=True),
        )

    @property
    def crs(self) -> CRS:
        return CRS.from_epsg(self.epsg)

    def crs_name(self) -> str:
        crs = self.crs
        name = crs.name
        return f"EPSG:{self.epsg} - {name}"

    def project(self, lon: float, lat: float) -> tuple[float, float]:
        x, y = self._fwd.transform(lon, lat)
        return float(x), float(y)

    def project_many(self, lons, lats) -> list[tuple[float, float]]:
        xs, ys = self._fwd.transform(lons, lats)
        return [(float(x), float(y)) for x, y in zip(xs, ys)]

    def unproject(self, x: float, y: float) -> tuple[float, float]:
        lon, lat = self._inv.transform(x, y)
        return float(lon), float(lat)


def gsd_from_metadata(
    altitude_m: float | None,
    width_px: int | None,
    focal_length_mm: float | None,
    focal_length_35mm: float | None,
    sensor_width_mm: float | None,
) -> tuple[float | None, str | None]:
    """Estimate ground sampling distance in metres per pixel.

    Two standard pinhole formulas, in order of preference:

    * known physical sensor width:  ``GSD = altitude * sensor_width / (focal * width_px)``
    * 35 mm equivalent focal length: ``GSD = altitude * 36 mm / (focal35 * width_px)``
      (36 mm is the full-frame reference width used to define the equivalent)

    Returns ``(None, None)`` when the required inputs are absent. The result is
    an *estimate from metadata*; it is never presented as a surveyed GSD.
    """
    if altitude_m is None or width_px is None or altitude_m <= 0:
        return None, None
    if sensor_width_mm and focal_length_mm and focal_length_mm > 0:
        return (altitude_m * sensor_width_mm) / (focal_length_mm * width_px), "sensor_width"
    if focal_length_35mm and focal_length_35mm > 0:
        return (altitude_m * 36.0) / (focal_length_35mm * width_px), "35mm_equiv"
    return None, None
