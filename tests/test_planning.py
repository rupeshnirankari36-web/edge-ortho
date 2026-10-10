"""Neighbour planning: GPS-guided candidate selection.

The claim being tested is the one the brief makes: GPS proximity removes most of the
O(n^2) comparisons without dropping the pairs that actually overlap. The tests use
synthetic frame records positioned on a UTM grid so the expected answer is known.
"""

from __future__ import annotations

import pytest

from edge_ortho.contracts import FrameRecord
from edge_ortho.plan.neighbours import plan_neighbours


def frame(idx: int, east: float, north: float, gsd: float = 0.02, w: int = 4000, h: int = 2250) -> FrameRecord:
    record = FrameRecord(
        frame_id=f"f{idx:03d}",
        path=f"/tmp/f{idx:03d}.jpg",
        filename=f"f{idx:03d}.jpg",
        bytes=1_000_000,
        accepted=True,
    )
    record.width = w
    record.height = h
    record.gsd_m = gsd
    record.footprint_w_m = w * gsd
    record.footprint_h_m = h * gsd
    record.projected_x = east
    record.projected_y = north
    return record


def test_transect_selects_neighbours_and_not_every_pair():
    # 12 frames 30 m apart along a line; the along-track footprint is 80 m, so each
    # frame overlaps several neighbours but nowhere near all of them.
    frames = [frame(i, east=i * 30.0, north=0.0) for i in range(12)]
    plan = plan_neighbours(frames, radius_factor=0.85, max_links=12, min_overlap=0.15)
    assert plan.candidate_pairs > 0
    assert plan.candidate_pairs < plan.all_pairs_possible
    assert plan.reduction_factor is not None and plan.reduction_factor > 1.0
    assert plan.radius_m is not None and plan.radius_m > 0
    assert plan.selection_method in {"gps_kdtree", "footprint_overlap", "sequential_fallback"}
    ids = {f.frame_id for f in frames}
    for pair in plan.neighbours:
        assert pair.source_id in ids and pair.target_id in ids
        assert pair.source_id != pair.target_id
        assert pair.distance_m <= plan.radius_m * 1.5


def test_every_neighbour_pair_is_unique_and_within_radius():
    frames = [frame(i, east=(i % 4) * 25.0, north=(i // 4) * 25.0) for i in range(16)]
    plan = plan_neighbours(frames, radius_factor=0.9)
    keys = [(p.source_id, p.target_id) for p in plan.neighbours]
    assert len(keys) == len(set(keys))
    for pair in plan.neighbours:
        src = next(f for f in frames if f.frame_id == pair.source_id)
        dst = next(f for f in frames if f.frame_id == pair.target_id)
        assert pair.distance_m == pytest.approx(
            ((src.projected_x - dst.projected_x) ** 2 + (src.projected_y - dst.projected_y) ** 2) ** 0.5,
            rel=1e-6,
        )


def test_distant_frames_are_not_paired():
    frames = [frame(0, 0.0, 0.0), frame(1, 5_000.0, 0.0)]
    plan = plan_neighbours(frames)
    assert plan.candidate_pairs == 0
    assert plan.notes  # the reason is stated


def test_single_frame_produces_no_graph():
    plan = plan_neighbours([frame(0, 0.0, 0.0)])
    assert plan.all_pairs_possible == 0
    assert plan.candidate_pairs == 0
    assert any("fewer than two" in n for n in plan.notes)


def test_frames_without_gps_are_excluded():
    with_gps = [frame(i, east=i * 30.0, north=0.0) for i in range(4)]
    no_gps = FrameRecord(frame_id="orphan", path="/tmp/o.jpg", filename="o.jpg", bytes=10, accepted=True)
    plan = plan_neighbours([*with_gps, no_gps])
    participating = {p.source_id for p in plan.neighbours} | {p.target_id for p in plan.neighbours}
    assert "orphan" not in participating


def test_max_links_caps_the_comparison_budget():
    frames = [frame(i, east=i * 5.0, north=0.0) for i in range(20)]
    capped = plan_neighbours(frames, radius_factor=6.0, max_links=3)
    assert capped.candidate_pairs <= 20 * 3
    assert capped.reduction_factor is not None


def test_overlap_estimate_is_present_when_geometry_allows():
    frames = [frame(i, east=i * 30.0, north=0.0) for i in range(6)]
    plan = plan_neighbours(frames)
    overlaps = [p.estimated_overlap for p in plan.neighbours if p.estimated_overlap is not None]
    assert overlaps, "footprint geometry should allow an overlap estimate"
    assert all(0.0 <= o <= 1.0 for o in overlaps)
    if plan.selection_method == "footprint_overlap":
        assert all(o >= 0.15 for o in overlaps)


def test_plan_reduction_factor_is_consistent_with_pair_count():
    frames = [frame(i, east=i * 22.0, north=0.0) for i in range(14)]
    plan = plan_neighbours(frames)
    assert plan.reduction_factor == pytest.approx(plan.all_pairs_possible / plan.candidate_pairs, rel=1e-6)
