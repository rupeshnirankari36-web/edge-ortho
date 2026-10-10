"""Ground footprint geometry.

An image footprint is modelled as a rotated rectangle on the UTM ground plane:

* the camera is treated as nadir (the brief scopes the MVP to mostly flat,
  nadir RGB surveys);
* ``yaw`` is the compass heading of the camera's forward axis;
* on the ground, forward = ``(sin yaw, cos yaw)`` and right = ``(cos yaw, -sin yaw)``
  in east/north metres.

These polygons do two jobs: they estimate ground overlap for pair selection and
they are exported as GeoJSON so the map viewer can draw the real flight
footprints. When a frame has no GSD estimate the polygon is unavailable and the
caller must fall back explicitly - we never invent a footprint size.
"""

from __future__ import annotations

import math

from ..contracts import FrameRecord

Point = tuple[float, float]
Polygon = list[Point]


def footprint_polygon(frame: FrameRecord) -> Polygon | None:
    """Return the four ground corners (east, north) or ``None`` if undetermined."""
    if (
        frame.projected_x is None
        or frame.projected_y is None
        or not frame.footprint_w_m
        or not frame.footprint_h_m
    ):
        return None
    yaw = math.radians(frame.yaw_deg or 0.0)
    fx, fy = math.sin(yaw), math.cos(yaw)  # forward (east, north)
    rx, ry = math.cos(yaw), -math.sin(yaw)  # right of forward
    hw, hh = frame.footprint_w_m / 2.0, frame.footprint_h_m / 2.0
    cx, cy = frame.projected_x, frame.projected_y

    def corner(r: float, f: float) -> Point:
        return (cx + r * hw * rx + f * hh * fx, cy + r * hw * ry + f * hh * fy)

    # clockwise from top-left in image space
    return [corner(-1, +1), corner(+1, +1), corner(+1, -1), corner(-1, -1)]


def polygon_area(poly: Polygon) -> float:
    """Absolute area of a simple polygon (shoelace formula)."""
    if len(poly) < 3:
        return 0.0
    total = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _inside(p: Point, a: Point, b: Point) -> bool:
    """True when p is on the inner (left) side of directed edge a->b."""
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0.0


def _line_intersection(p1: Point, p2: Point, a: Point, b: Point) -> Point:
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = a
    x4, y4 = b
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-12:
        return p2
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denom
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denom
    return (px, py)


def _ensure_ccw(poly: Polygon) -> Polygon:
    signed = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        signed += x1 * y2 - x2 * y1
    return poly if signed >= 0 else list(reversed(poly))


def polygon_intersection(subject: Polygon, clip: Polygon) -> Polygon:
    """Sutherland-Hodgman clip of `subject` against convex `clip`."""
    if len(subject) < 3 or len(clip) < 3:
        return []
    output = _ensure_ccw(list(subject))
    clip_ccw = _ensure_ccw(list(clip))
    n = len(clip_ccw)
    for i in range(n):
        if not output:
            return []
        a, b = clip_ccw[i], clip_ccw[(i + 1) % n]
        input_list = output
        output = []
        for j in range(len(input_list)):
            current = input_list[j]
            previous = input_list[j - 1]
            cur_in = _inside(current, a, b)
            prev_in = _inside(previous, a, b)
            if cur_in:
                if not prev_in:
                    output.append(_line_intersection(previous, current, a, b))
                output.append(current)
            elif prev_in:
                output.append(_line_intersection(previous, current, a, b))
    return output


def overlap_fraction(poly_a: Polygon | None, poly_b: Polygon | None) -> float | None:
    """Intersection area divided by the smaller footprint area.

    ``None`` when either footprint is unknown - the caller must treat that as
    "overlap not measurable" rather than assuming a value.
    """
    if not poly_a or not poly_b:
        return None
    area_a = polygon_area(poly_a)
    area_b = polygon_area(poly_b)
    smaller = min(area_a, area_b)
    if smaller <= 0:
        return None
    inter = polygon_area(polygon_intersection(poly_a, poly_b))
    return max(0.0, min(1.0, inter / smaller))


def polygon_diagonal(frame: FrameRecord) -> float | None:
    if not frame.footprint_w_m or not frame.footprint_h_m:
        return None
    return math.hypot(frame.footprint_w_m, frame.footprint_h_m)


def footprint_geojson(frames: list[FrameRecord]) -> dict:
    """FeatureCollection of image footprints for the Leaflet overlay."""
    features = []
    for f in frames:
        poly = footprint_polygon(f)
        if not poly:
            continue
        ring = [[round(x, 3), round(y, 3)] for x, y in poly]
        ring.append(ring[0])
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "frame_id": f.frame_id,
                    "filename": f.filename,
                    "yaw_deg": f.yaw_deg,
                    "gsd_m": f.gsd_m,
                    "altitude_m": f.altitude_m,
                    "captured_at": f.captured_at,
                },
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        )
    return {"type": "FeatureCollection", "features": features}


def flight_path_geojson(frames: list[FrameRecord]) -> dict:
    pts = [
        [round(f.projected_x, 3), round(f.projected_y, 3)]
        for f in frames
        if f.projected_x is not None and f.projected_y is not None
    ]
    if len(pts) < 2:
        return {"type": "FeatureCollection", "features": []}
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"kind": "flight_path", "frames": len(pts)},
                "geometry": {"type": "LineString", "coordinates": pts},
            }
        ],
    }
