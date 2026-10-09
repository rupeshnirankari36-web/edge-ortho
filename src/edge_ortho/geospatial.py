"""Small, dependency-free geospatial primitives for the Rupesh workstream.

The module deliberately keeps rasterio/pyproj integration at the boundary so
contracts and tests can run on a clean laptop before the heavier GIS stack is
installed.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Iterable


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float

    def validate(self) -> None:
        if not (-90.0 <= self.lat <= 90.0):
            raise ValueError(f"latitude out of range: {self.lat}")
        if not (-180.0 <= self.lon <= 180.0):
            raise ValueError(f"longitude out of range: {self.lon}")


@dataclass(frozen=True)
class Bounds:
    west: float
    south: float
    east: float
    north: float

    def validate(self) -> None:
        if self.west >= self.east or self.south >= self.north:
            raise ValueError("bounds must have positive width and height")

    @property
    def width(self) -> float:
        return self.east - self.west

    @property
    def height(self) -> float:
        return self.north - self.south


@dataclass(frozen=True)
class Canvas:
    bounds: Bounds
    pixel_size_m: float
    width_px: int
    height_px: int

    def validate(self) -> None:
        self.bounds.validate()
        if self.pixel_size_m <= 0:
            raise ValueError("pixel_size_m must be positive")
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError("canvas dimensions must be positive")

    def world_to_pixel(self, x: float, y: float) -> tuple[float, float]:
        """Convert projected metres to north-up pixel coordinates."""
        self.validate()
        col = (x - self.bounds.west) / self.pixel_size_m
        row = (self.bounds.north - y) / self.pixel_size_m
        return col, row

    def pixel_to_world(self, col: float, row: float) -> tuple[float, float]:
        """Convert north-up pixel coordinates to projected metres."""
        self.validate()
        x = self.bounds.west + col * self.pixel_size_m
        y = self.bounds.north - row * self.pixel_size_m
        return x, y


def validate_points(points: Iterable[GeoPoint]) -> list[GeoPoint]:
    result = list(points)
    if not result:
        raise ValueError("at least one geotagged frame is required")
    for point in result:
        point.validate()
    return result


def utm_epsg(point: GeoPoint) -> int:
    """Return the WGS84 UTM EPSG code for a point."""
    point.validate()
    zone = floor((point.lon + 180.0) / 6.0) + 1
    zone = min(60, max(1, zone))
    return (32600 if point.lat >= 0 else 32700) + zone


def bounds_from_projected(points: Iterable[tuple[float, float]], padding_m: float = 0.0) -> Bounds:
    coords = list(points)
    if not coords:
        raise ValueError("at least one projected point is required")
    if padding_m < 0:
        raise ValueError("padding_m cannot be negative")
    xs, ys = zip(*coords)
    bounds = Bounds(min(xs) - padding_m, min(ys) - padding_m,
                    max(xs) + padding_m, max(ys) + padding_m)
    bounds.validate()
    return bounds
