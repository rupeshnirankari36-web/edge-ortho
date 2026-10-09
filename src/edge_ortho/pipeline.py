"""
EdgeOrtho – full processing pipeline orchestrator.

Runs: Ingest → Validate GPS → Build Neighbour Graph → Match Pairs
      → Align → Compose → Georeference

Measures wall-clock time and peak RSS RAM for each stage.
Saves per-stage results and a metrics JSON to the project directory.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import psutil

from ..ingest.reader import ingest_folder, ImageMeta
from ..ingest.neighbours import build_neighbour_graph, NeighbourPair
from ..align.matcher import match_pair, MatchResult
from ..compose.mosaic import compose_mosaic, ComposeResult


def _rss_mb() -> float:
    return psutil.Process().memory_info().rss / (1024 ** 2)


def _timed(fn, *args, **kwargs):
    """Run fn(*args, **kwargs), return (result, elapsed_s, peak_rss_mb)."""
    t0 = time.perf_counter()
    rss_before = _rss_mb()
    result = fn(*args, **kwargs)
    elapsed = time.perf_counter() - t0
    peak = max(_rss_mb(), rss_before)
    return result, elapsed, peak


def run_pipeline(
    project_dir: str,
    raw_dir: str,
    save_callback=None,   # optional callable(stage, status, meta_update)
    max_gps_distance_m: float = 120.0,
    max_neighbours: int = 6,
    match_pixels: int = 600_000,
    matcher: str = "orb",
    transform_model: str = "affine",
    debug_matches: bool = False,
) -> dict[str, Any]:
    """
    Execute the full EdgeOrtho processing pipeline.
    
    Returns a final metrics dictionary. Intermediate state is saved to
    project_dir/pipeline_state.json after each stage.
    """
    output_dir = os.path.join(project_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    state: dict[str, Any] = {
        "stages": {
            "ingest": "running",
            "validate_gps": "pending",
            "plan_neighbours": "pending",
            "match_features": "pending",
            "align": "pending",
            "compose": "pending",
            "georeference": "pending",
            "export": "pending",
        },
        "metrics": {
            "peak_ram_mb": 0.0,
            "total_time_s": 0.0,
        },
        "diagnostics": {},
        "error": None,
    }

    def save_state():
        with open(os.path.join(project_dir, "pipeline_state.json"), "w") as f:
            json.dump(state, f, indent=2, default=str)
        if save_callback:
            save_callback(state)

    total_start = time.perf_counter()
    peak_ram = _rss_mb()

    # --- Stage 1: Ingest ---
    save_state()
    images, elapsed, rss = _timed(ingest_folder, raw_dir)
    peak_ram = max(peak_ram, rss)

    valid_images = [img for img in images if img.readable]
    gps_images = [img for img in images if img.has_gps]
    rejected = [img for img in images if not img.has_gps or not img.readable]

    state["diagnostics"]["ingest"] = {
        "total_found": len(images),
        "readable": len(valid_images),
        "with_gps": len(gps_images),
        "rejected": len(rejected),
        "rejected_reasons": [
            {"filename": img.filename, "reason": img.rejection_reason}
            for img in rejected
        ],
        "elapsed_s": elapsed,
    }
    state["stages"]["ingest"] = "completed"
    state["stages"]["validate_gps"] = "completed" if gps_images else "failed"

    if not valid_images:
        state["error"] = "No readable images found in raw directory."
        state["stages"]["ingest"] = "failed"
        save_state()
        return state

    if len(gps_images) < 2:
        state["error"] = "Fewer than 2 images have GPS metadata. Cannot build neighbour graph or georeference."
        state["stages"]["validate_gps"] = "failed"
        save_state()
        return state

    # --- Stage 2: Plan Neighbours ---
    state["stages"]["plan_neighbours"] = "running"
    save_state()

    pairs, elapsed, rss = _timed(
        build_neighbour_graph, gps_images, max_gps_distance_m, max_neighbours
    )
    peak_ram = max(peak_ram, rss)

    state["diagnostics"]["plan_neighbours"] = {
        "candidate_pairs": len(pairs),
        "max_distance_m": max_gps_distance_m,
        "elapsed_s": elapsed,
        "pairs": [
            {"a": p.filename_a, "b": p.filename_b, "dist_m": round(p.distance_m, 2)}
            for p in pairs
        ],
    }
    state["stages"]["plan_neighbours"] = "completed" if pairs else "failed"

    if not pairs:
        state["error"] = f"No candidate pairs within {max_gps_distance_m}m. Images may be too far apart or missing GPS."
        save_state()
        return state

    # --- Stage 3: Match Features ---
    state["stages"]["match_features"] = "running"
    save_state()

    match_results: list[MatchResult] = []
    match_start = time.perf_counter()
    match_diag = []

    # Build a lookup from filename → filepath using the full ingest list
    path_lookup = {img.filename: img.filepath for img in images}

    debug_dir = os.path.join(output_dir, "matches_debug") if debug_matches else None

    for pair in pairs:
        path_a = path_lookup.get(pair.filename_a, "")
        path_b = path_lookup.get(pair.filename_b, "")
        if not path_a or not path_b:
            continue
        dbg_path = (
            os.path.join(debug_dir, f"{pair.filename_a}_vs_{pair.filename_b}.jpg")
            if debug_dir
            else None
        )
        mr = match_pair(
            path_a,
            path_b,
            target_pixels=match_pixels,
            method=matcher,
            model=transform_model,
            save_debug_path=dbg_path,
        )
        match_results.append(mr)
        match_diag.append({
            "a": mr.filename_a,
            "b": mr.filename_b,
            "kp_a": mr.keypoints_a,
            "kp_b": mr.keypoints_b,
            "raw_matches": mr.raw_matches,
            "ratio_passed": mr.ratio_passed,
            "inliers": mr.inliers,
            "inlier_ratio": round(mr.inlier_ratio, 4),
            "reprojection_error_px": round(mr.reprojection_error_px, 3),
            "model": mr.model,
            "status": mr.status,
            "success": mr.success,
            "error": mr.error,
        })

    match_elapsed = time.perf_counter() - match_start
    peak_ram = max(peak_ram, _rss_mb())

    successful_matches = [mr for mr in match_results if mr.success]

    state["diagnostics"]["match_features"] = {
        "pairs_attempted": len(pairs),
        "pairs_succeeded": len(successful_matches),
        "pairs_failed": len(pairs) - len(successful_matches),
        "elapsed_s": match_elapsed,
        "details": match_diag,
    }
    state["stages"]["match_features"] = "completed" if successful_matches else "failed"
    state["stages"]["align"] = "completed" if successful_matches else "skipped"

    if not successful_matches:
        state["error"] = "No image pairs could be matched. Check image overlap and quality."
        save_state()
        return state

    # --- Stage 4: Compose ---
    state["stages"]["compose"] = "running"
    save_state()

    compose_result, elapsed, rss = _timed(
        compose_mosaic, gps_images, match_results, output_dir, ref_idx=0
    )
    peak_ram = max(peak_ram, rss)

    state["stages"]["compose"] = "completed" if compose_result.success else "failed"

    if not compose_result.success:
        state["error"] = compose_result.error
        save_state()
        return state

    # --- Stage 5: Georeference / Export ---
    state["stages"]["georeference"] = "completed" if compose_result.is_georeferenced else "skipped"
    state["stages"]["export"] = "completed" if compose_result.mosaic_path else "failed"

    state["diagnostics"]["compose"] = {
        "mosaic_path": compose_result.mosaic_path,
        "geotiff_path": compose_result.geotiff_path,
        "width_px": compose_result.width_px,
        "height_px": compose_result.height_px,
        "file_bytes": compose_result.file_bytes,
        "crs": compose_result.crs,
        "bounds_wgs84": compose_result.bounds_wgs84,
        "is_georeferenced": compose_result.is_georeferenced,
        "georef_warning": compose_result.georef_warning,
        "elapsed_s": elapsed,
    }

    total_elapsed = time.perf_counter() - total_start
    state["metrics"]["peak_ram_mb"] = round(peak_ram, 2)
    state["metrics"]["total_time_s"] = round(total_elapsed, 2)
    state["metrics"]["accepted_frames"] = len(gps_images)
    state["metrics"]["rejected_frames"] = len(rejected)
    state["metrics"]["candidate_pairs"] = len(pairs)
    state["metrics"]["matched_pairs"] = len(successful_matches)
    state["metrics"]["output_bytes"] = compose_result.file_bytes

    # Bandwidth estimate at common link speeds
    out_bytes = compose_result.file_bytes or 0
    in_bytes = sum(img.file_bytes for img in images)
    for speed_mbps in [1, 5, 20]:
        speed_bps = speed_mbps * 1_000_000
        state["metrics"][f"upload_raw_{speed_mbps}mbps_s"] = round(in_bytes * 8 / speed_bps, 1)
        state["metrics"][f"download_result_{speed_mbps}mbps_s"] = round(out_bytes * 8 / speed_bps, 1)

    save_state()
    return state
