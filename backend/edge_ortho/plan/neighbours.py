"""Stage 3 - plan neighbours.

The brief's central edge optimisation: "Uses GPS to find nearby image candidates
instead of comparing every image with every other image."

* A :class:`scipy.spatial.cKDTree` indexes projected image centres.
* Candidate radius adapts to the *measured* footprint diagonal, so the graph
  scales with GSD instead of a magic constant.
* Every candidate pair is then gated on a real convex-polygon overlap area
  (see :mod:`edge_ortho.geo.footprints`). Pairs below the threshold are dropped
  and counted, so the reduction is auditable.
* If the footprint is unknown (no GSD) the module falls back to a nearest
  neighbour spacing radius and labels every pair ``sequential_fallback``.

No GPS means no graph: frames without coordinates were already rejected during
validation, and this module refuses to guess adjacency from filenames alone.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

import numpy as np
from scipy.spatial import cKDTree

from ..contracts import FrameRecord, NeighbourRecord
from ..geo.footprints import footprint_polygon, overlap_fraction, polygon_diagonal


@dataclass
class PlanResult:
    neighbours: list[NeighbourRecord] = field(default_factory=list)
    selection_method: str = "gps_kdtree"
    radius_m: float | None = None
    all_pairs_possible: int = 0
    pairs_evaluated: int = 0
    pairs_below_overlap: int = 0
    reduction_factor: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def candidate_pairs(self) -> int:
        return len(self.neighbours)

    def to_dict(self) -> dict:
        return {
            "selection_method": self.selection_method,
            "radius_m": self.radius_m,
            "candidate_pairs": self.candidate_pairs,
            "all_pairs_possible": self.all_pairs_possible,
            "pairs_evaluated": self.pairs_evaluated,
            "pairs_below_overlap": self.pairs_below_overlap,
            "reduction_factor": self.reduction_factor,
            "notes": self.notes,
            "neighbours": [n.__dict__ for n in self.neighbours],
        }


def _auto_radius(frames: list[FrameRecord]) -> tuple[float, str]:
    """Radius from footprints when available, otherwise from observed spacing."""
    diagonals = [d for d in (polygon_diagonal(f) for f in frames) if d]
    if diagonals:
        return statistics.median(diagonals), "footprint_diagonal"
    pts = [(f.projected_x, f.projected_y) for f in frames if f.projected_x is not None]
    if len(pts) < 2:
        return 0.0, "unavailable"
    tree = cKDTree(np.asarray(pts))
    dists, _ = tree.query(np.asarray(pts), k=2)
    nearest = [d[1] for d in dists if d[1] > 0]
    if not nearest:
        return 0.0, "unavailable"
    return statistics.median(nearest) * 2.0, "neighbour_spacing"


def plan_neighbours(
    frames: list[FrameRecord],
    radius_factor: float = 0.85,
    max_links: int = 12,
    min_overlap: float = 0.15,
) -> PlanResult:
    """Build the candidate pair graph for the accepted frames."""
    result = PlanResult()
    usable = [f for f in frames if f.projected_x is not None and f.projected_y is not None]
    n = len(usable)
    result.all_pairs_possible = n * (n - 1) // 2
    if n < 2:
        result.notes.append("fewer than two geotagged frames: no neighbour graph")
        return result

    base_radius, radius_source = _auto_radius(usable)
    if base_radius <= 0:
        result.notes.append("no usable footprint or spacing: neighbour graph unavailable")
        return result

    radius = base_radius * radius_factor
    result.radius_m = radius
    result.notes.append(
        f"candidate radius {radius:.1f} m = {radius_factor:g} x {radius_source} "
        f"({base_radius:.1f} m)"
    )

    coords = np.asarray([[f.projected_x, f.projected_y] for f in usable], dtype=np.float64)
    tree = cKDTree(coords)
    polygons = {f.frame_id: footprint_polygon(f) for f in usable}
    footprints_available = any(polygons.values())
    if not footprints_available:
        result.selection_method = "sequential_fallback"
        result.notes.append(
            "footprint polygons unavailable (no GSD estimate): overlap is not measurable, "
            "pairs are selected by distance only and labelled as a fallback"
        )

    candidate_set: set[tuple[str, str]] = set()
    evaluated = 0
    below = 0
    links: dict[str, list[tuple[float, str]]] = {f.frame_id: [] for f in usable}

    for i, frame in enumerate(usable):
        idxs = tree.query_ball_point(coords[i], radius)
        for j in idxs:
            if j == i:
                continue
            other = usable[j]
            a, b = sorted((frame.frame_id, other.frame_id))
            if (a, b) in candidate_set:
                continue
            d = float(math.dist(coords[i], coords[j]))
            evaluated += 1
            ov = overlap_fraction(polygons[frame.frame_id], polygons[other.frame_id])
            if ov is not None and ov < min_overlap:
                below += 1
                continue
            candidate_set.add((a, b))
            links[frame.frame_id].append((d, other.frame_id))
            links[other.frame_id].append((d, frame.frame_id))

    # Cap the degree of the graph to keep matching bounded on large datasets.
    kept: set[tuple[str, str]] = set()
    for fid, lst in links.items():
        for _d, other in sorted(lst)[:max_links]:
            kept.add(tuple(sorted((fid, other))))

    dropped_by_cap = len(candidate_set) - len(kept)

    by_id = {f.frame_id: f for f in usable}
    records: list[NeighbourRecord] = []
    for a, b in sorted(kept):
        fa, fb = by_id[a], by_id[b]
        d = float(math.dist((fa.projected_x, fa.projected_y), (fb.projected_x, fb.projected_y)))
        ov = overlap_fraction(polygons[a], polygons[b])
        records.append(
            NeighbourRecord(
                source_id=a,
                target_id=b,
                distance_m=d,
                estimated_overlap=ov,
                selection=result.selection_method,
            )
        )

    result.neighbours = records
    result.pairs_evaluated = evaluated
    result.pairs_below_overlap = below
    if result.all_pairs_possible:
        result.reduction_factor = result.all_pairs_possible / max(1, len(records))
    if dropped_by_cap:
        result.notes.append(f"{dropped_by_cap} pair(s) dropped by the {max_links}-link degree cap")

    overlaps = [r.estimated_overlap for r in records if r.estimated_overlap is not None]
    if overlaps:
        result.notes.append(
            f"estimated ground overlap: min {min(overlaps):.0%}, "
            f"median {statistics.median(overlaps):.0%}, max {max(overlaps):.0%}"
        )
    return result
