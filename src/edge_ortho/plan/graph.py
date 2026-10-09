"""Spatial KD-Tree neighbor graph construction for edge-efficient pairing."""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from ..ingest.models import FrameRecord


@dataclass
class NeighborPair:
    source_id: str
    target_id: str
    distance_meters: float


def build_neighbor_graph(
    records: Sequence[FrameRecord],
    k_neighbors: int = 6,
    max_distance_meters: float = 80.0,
) -> list[NeighborPair]:
    """
    Constructs a KD-Tree on projected UTM coordinates to find candidate pairs
    for feature matching within physical overlap proximity, cutting O(N^2) to O(N log N).
    """
    if len(records) < 2:
        return []

    # Extract UTM coordinates
    coords = []
    id_map = []
    for r in records:
        if r.utm_easting is not None and r.utm_northing is not None:
            coords.append([r.utm_easting, r.utm_northing])
            id_map.append(r.frame_id)
        else:
            # Fallback approximate equirectangular meters if UTM missing
            coords.append([r.lon * 111320.0 * np.cos(np.radians(r.lat)), r.lat * 110540.0])
            id_map.append(r.frame_id)

    coords_arr = np.array(coords, dtype=np.float64)
    tree = cKDTree(coords_arr)

    # Query k+1 neighbors (as index 0 will be the point itself)
    k_query = min(k_neighbors + 1, len(records))
    distances, indices = tree.query(coords_arr, k=k_query, distance_upper_bound=max_distance_meters)

    seen_pairs: set[tuple[str, str]] = set()
    neighbor_pairs: list[NeighborPair] = []

    for i in range(len(records)):
        src_id = id_map[i]
        for dist, idx in zip(distances[i], indices[i]):
            # cKDTree returns idx == len(coords_arr) when no point within upper bound
            if idx >= len(coords_arr) or idx == i:
                continue
            tgt_id = id_map[idx]
            pair_key = tuple(sorted([src_id, tgt_id]))
            if pair_key not in seen_pairs:
                seen_pairs.add(pair_key)
                neighbor_pairs.append(
                    NeighborPair(
                        source_id=pair_key[0],
                        target_id=pair_key[1],
                        distance_meters=float(dist),
                    )
                )

    # Sort pairs by distance for deterministic matching order
    neighbor_pairs.sort(key=lambda p: p.distance_meters)
    return neighbor_pairs
