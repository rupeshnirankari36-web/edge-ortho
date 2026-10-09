"""Coordinate Reference System (CRS) management and UTM transformations."""

import math
from collections.abc import Sequence

import pyproj

from ..ingest.models import FrameRecord


def latlon_to_utm_epsg(lat: float, lon: float) -> int:
    """Computes the WGS84 UTM EPSG code for given (lat, lon)."""
    zone = int(math.floor((lon + 180.0) / 6.0)) + 1
    if zone < 1:
        zone = 1
    elif zone > 60:
        zone = 60

    if lat >= 0:
        return 32600 + zone
    else:
        return 32700 + zone


def project_records_to_utm(records: Sequence[FrameRecord]) -> int:
    """
    Determines the dominant UTM zone for the flight records,
    projects all GPS coordinates to UTM Easting and Northing (meters),
    and sets utm_easting, utm_northing, utm_epsg in-place.
    Returns the chosen UTM EPSG code.
    """
    if not records:
        return 4326

    # Use median lat and lon to determine central UTM zone
    median_lat = sorted(r.lat for r in records)[len(records) // 2]
    median_lon = sorted(r.lon for r in records)[len(records) // 2]
    epsg_code = latlon_to_utm_epsg(median_lat, median_lon)

    # Initialize PyProj Transformer from WGS84 (EPSG:4326) to UTM
    # always_xy=True ensures (lon, lat) order
    transformer = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg_code}", always_xy=True)

    for rec in records:
        east, north = transformer.transform(rec.lon, rec.lat)
        rec.utm_easting = float(east)
        rec.utm_northing = float(north)
        rec.utm_epsg = epsg_code

    return epsg_code
