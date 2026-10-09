from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List

import numpy as np
from scipy.spatial import cKDTree

from ..ingest.reader import ImageMeta

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in metres between two GPS coordinates."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def latlon_to_utm_approx(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """
    Project lat/lon to local tangent plane in meters centered at (lat0, lon0).
    Equirectangular projection accurate within local flight blocks.
    """
    dlat = math.radians(lat - lat0)
    dlon = math.radians(lon - lon0)
    mean_lat = math.radians((lat + lat0) / 2.0)
    x = EARTH_RADIUS_M * dlon * math.cos(mean_lat)
    y = EARTH_RADIUS_M * dlat
    return x, y


@dataclass
class NeighbourPair:
    idx_a: int
    idx_b: int
    distance_m: float
    filename_a: str
    filename_b: str


def build_neighbour_graph(
    images: List[ImageMeta],
    max_distance_m: float = 120.0,
    max_neighbours: int = 6,
    include_flight_order: bool = True,
    fallback_expansion: bool = True,
) -> List[NeighbourPair]:
    """
    Build candidate image pairs using GPS proximity via scipy.spatial.cKDTree.

    Features:
    - O(N log N) spatial query using cKDTree.
    - Capped neighbour degree (max_neighbours) to prevent quadratic pair explosion.
    - Deterministic ordering by (distance_m, filename_a, filename_b).
    - Optional flight-order neighbor edge connecting sequential images in track.
    - Fallback radius expansion if sparse track results in disconnected frames.
    """
    gps_images = [(i, img) for i, img in enumerate(images) if img.has_gps and img.lat is not None and img.lon is not None]

    if len(gps_images) < 2:
        return []

    lat0 = sum(img.lat for _, img in gps_images) / len(gps_images)
    lon0 = sum(img.lon for _, img in gps_images) / len(gps_images)

    coords = np.array([
        latlon_to_utm_approx(img.lat, img.lon, lat0, lon0)  # type: ignore[arg-type]
        for _, img in gps_images
    ], dtype=np.float64)

    tree = cKDTree(coords)
    effective_radius = max_distance_m

    # Fallback radius expansion for sparse GPS tracks (within realistic flight line limits, up to 1.5x)
    if fallback_expansion:
        counts = [len(tree.query_ball_point(pt, r=effective_radius)) - 1 for pt in coords]
        if any(c == 0 for c in counts):
            expanded = effective_radius * 1.5
            expanded_counts = [len(tree.query_ball_point(pt, r=expanded)) - 1 for pt in coords]
            # Only adopt expanded radius if it actually finds candidates without extreme separation
            if any(c > 0 for c in expanded_counts):
                effective_radius = expanded

    neighbour_count: dict[int, int] = {i: 0 for i, _ in gps_images}
    pairs_dict: dict[tuple[int, int], NeighbourPair] = {}

    # 1. Add sequential flight-order edges if requested and within proximity
    if include_flight_order and len(gps_images) > 1:
        for seq in range(len(gps_images) - 1):
            ia, img_a = gps_images[seq]
            ib, img_b = gps_images[seq + 1]
            d = haversine_m(img_a.lat, img_a.lon, img_b.lat, img_b.lon)  # type: ignore[arg-type]
            if d <= effective_radius:
                key = (min(ia, ib), max(ia, ib))
                pairs_dict[key] = NeighbourPair(
                    idx_a=key[0],
                    idx_b=key[1],
                    distance_m=d,
                    filename_a=images[key[0]].filename,
                    filename_b=images[key[1]].filename,
                )
                neighbour_count[ia] += 1
                neighbour_count[ib] += 1

    # 2. Add spatial cKDTree neighbors up to max_neighbours
    for pos, (orig_idx_a, img_a) in enumerate(gps_images):
        pt = coords[pos]
        # Query up to max_neighbours + 1 nearest points within radius
        dists, indices = tree.query(pt, k=min(len(gps_images), max_neighbours * 2 + 1), distance_upper_bound=effective_radius)
        if not isinstance(dists, np.ndarray):
            dists = np.array([dists])
            indices = np.array([indices])

        for d_approx, neighbor_pos in zip(dists, indices):
            if neighbor_pos >= len(gps_images) or neighbor_pos == pos:
                continue
            orig_idx_b, img_b = gps_images[neighbor_pos]
            key = (min(orig_idx_a, orig_idx_b), max(orig_idx_a, orig_idx_b))
            if key in pairs_dict:
                continue
            if neighbour_count[orig_idx_a] >= max_neighbours or neighbour_count[orig_idx_b] >= max_neighbours:
                continue

            actual_d = haversine_m(img_a.lat, img_a.lon, img_b.lat, img_b.lon)  # type: ignore[arg-type]
            pairs_dict[key] = NeighbourPair(
                idx_a=key[0],
                idx_b=key[1],
                distance_m=actual_d,
                filename_a=images[key[0]].filename,
                filename_b=images[key[1]].filename,
            )
            neighbour_count[orig_idx_a] += 1
            neighbour_count[orig_idx_b] += 1

    # Deterministic sorting: distance ascending, then filename_a, then filename_b
    return sorted(
        pairs_dict.values(),
        key=lambda p: (round(p.distance_m, 4), p.filename_a, p.filename_b)
    )
