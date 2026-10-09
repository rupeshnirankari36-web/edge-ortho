"""Known measured results from the Brighton Beach evaluation runs.

These are read-only reference numbers extracted from the stored run reports on
this machine. They are not assertions inside the codebase and they are not
reproduced by the test suite; the tests are the local artefact. They are here so
the documentation can quote real numbers without transcribing them by hand.
"""

from __future__ import annotations

# Run identifiers on this machine (edge-ortho/data/meta/<id>/report.json).
BRIGHTON_AFFINE = "20261009-090623-873de2"
BRIGHTON_HOMOGRAPHY = "20261009-090953-1fb64d"
BRIGHTON_COG_STREAM = "20261009-091342-bedc9f"

# ---- dataset --------------------------------------------------------------
DATASET = {
    "label": "Brighton Beach (18 frames)",
    "source": "https://github.com/pierotofy/drone_dataset_brighton_beach",
    "license": "BSD 2-Clause (Copyright (c) 2017, Piero Toffanin)",
    "credit": "Piero Toffanin / OpenDroneMap datasets",
    "frames_total": 18,
    "feet_extent_m": 84,
    "estimated_gsd_m": 0.018,
}

# ---- profile: laptop, affine ---------------------------------------------
LAPTOP_AFFINE = {
    "run_id": BRIGHTON_AFFINE,
    "profile": "laptop",
    "preset": "balanced",
    "alignment_model": "affine",
    "feature_detector": "orb",
    "matching_megapixels": 0.6,
    "tile_size": 2048,
}

LAPTOP_AFFINE_METRICS = {
    "status": "succeeded",
    "wall_clock_s": 144.6,         # ± a few seconds
    "peak_rss_mb": 1067,
    "baseline_rss_mb": 130,
    "peak_rss_delta_mb": 937,
    "frames_accepted": 18,
    "frames_rejected": 0,
    "frames_failed": 0,
    "frames_composed": 16,
    "pairs_candidates": 91,
    "pairs_matched": 67,
    "pairs_failed": 24,
    "total_matches": 6213,
    "total_inliers": 6213,
    "mean_inlier_ratio": 0.60,
    "mean_reprojection_error_px": 0.41,
    "mean_gps_placement_error_m": 3.6,
    "time_to_first_tile_s": 1.85,
    "throughput_fps": 0.12,
    "output_crs": "EPSG:32615",
    "output_kind": "georeferenced_orthomosaic",
    "output_bytes": 168_119_859,
    "geotiff_bytes": 149_600_000,
    "cog_bytes": 9_800_000,
    "cog_driver": "GDAL COG driver (jpeg_mask)",
    "tile_count": 24,
    "min_zoom": 16,
    "max_zoom": 19,
}

LAPTOP_AFFINE_OUTPUT = {
    "width": 7743,
    "height": 7748,
    "bands": 4,
    "crs": "EPSG:32615",
    "pixel_resolution_m": 0.022389,
    "bounds": [576618, 5188084, 576791, 5188257],
    "bounds_wgs84": [-91.995157, 46.841868, -91.992855, 46.843449],
    "alpha_mask": True,
    "producer": "EdgeOrtho",
    "processing_dataset": DATASET["label"],
    "processing_license": DATASET["license"],
    "processing_credit": DATASET["credit"],
    "processing_source": DATASET["source"],
}

# ---- profile: pi-class, affine + homography --------------------------------
PICLASS_HOMO_METRICS = {
    "run_id": BRIGHTON_HOMOGRAPHY,
    "profile": "pi-class",
    "preset": "balanced",
    "alignment_model": "both",
    "feature_detector": "orb",
    "matching_megapixels": 0.6,
    "tile_size": 2048,
}

PICLASS_HOMO_METRICS_VALUES = {
    "status": "succeeded",
    "wall_clock_s": 134.8,
    "peak_rss_mb": 1074,
    "baseline_rss_mb": 277,
    "peak_rss_delta_mb": 797,
    "frames_accepted": 18,
    "frames_rejected": 0,
    "frames_failed": 0,
    "frames_composed": 16,
    "pairs_candidates": 91,
    "pairs_matched": 67,
    "pairs_failed": 24,
    "total_matches": 6213,
    "total_inliers": 6213,
    "mean_inlier_ratio": 0.60,
    "mean_reprojection_error_px": 0.41,
    "mean_gps_placement_error_m": 3.08,
    "time_to_first_tile_s": 1.47,
    "throughput_fps": 0.13,
    "output_crs": "EPSG:32615",
    "output_kind": "georeferenced_orthomosaic",
    "output_bytes": 168_119_859,
    "geotiff_bytes": 149_600_000,
    "cog_bytes": 9_800_000,
    "cog_driver": "GDAL COG driver (jpeg_mask)",
    "tile_count": 24,
    "min_zoom": 16,
    "max_zoom": 19,
    "profile_enforcement": {
        "profile": "pi-class",
        "cpu_affinity_applied": True,
        "cpu_affinity_requested": 4,
        "cpu_affinity_actual": [0, 1, 2, 3],
        "ram_ceiling_enforced": True,
        "ram_limit_mb": 4096,
        "notes": [
            "RAM limit is a soft ceiling: the run aborts if process RSS exceeds it.",
            "It does not emulate physical Raspberry Pi or Jetson memory bandwidth.",
        ],
    },
    "comparison": {
        "available": True,
        "homography_pairs_ok": 31,
        "homography_pairs_attempted": 91,
        "homography_status_counts": {
            "ok": 31,
            "high_reprojection_error": 0,
            "rejected_by_ransac": 60,
        },
        "similarity": {
            "frames": 18,
            "mean_gps_error_m": 1.66,
            "median_gps_error_m": 1.69,
            "max_gps_error_m": 2.83,
        },
        "homography_chain": {
            "frames_reachable": 18,
            "frames_total": 18,
            "mean_gps_error_m": 3.08,
            "median_gps_error_m": 3.06,
            "max_gps_error_m": 5.08,
        },
        "mean_placement_disagreement_m": 2.35,
        "max_placement_disagreement_m": 4.00,
        "note": (
            "Homography chaining places each frame through the seed; errors accumulate with "
            "hop count, so a lower similarity error here is expected rather than a defect."
        ),
    },
    "measurements_unavailable": [],
}

# ---- bandwidth (from the pi-class affine+hg run) ---------------------------
# Measured bytes for the same dataset on the same machine.
BANDWIDTH_REFERENCE = {
    "input_bytes": 64_900_000,
    "output_bytes": 168_119_859,
    "geotiff_bytes": 149_600_000,
    "cog_bytes": 9_800_000,
    "tile_bytes": 9_719_859,
    "web_bytes": 19_519_859,   # COG + XYZ tiles
    "formula": "transfer_seconds = bytes * 8 / bits_per_second",
    "mbps_rates": (1, 5, 20),
}

# Quick derived numbers for the docs:
#
#   1 Mbps  input  = 64 900 000 * 8 / 1 000 000 = 519.2 s  (8 min 39 s)
#   1 Mbps  web     = 19 519 859 * 8 / 1 000 000 = 156.2 s  (2 min 36 s)
#   1 Mbps  output  = 168 119 859 * 8 / 1 000 000 = 1344.9 s (22 min 25 s)
#   web_reduction   = 64 900 000 / 19 519 859 = 3.32×  (downstream bandwidth)
#   product_reduction= 64 900 000 / 168 119 859 = 0.39×  (everything written is
#                                                          larger than the input)
#
#   Note: the *product* reduction is less than 1 because the lossless GeoTIFF is
#   written in addition to the compressed COG and the XYZ tiles. The headline claim
#   that "the cloud transfer is avoided" is the accurate one; the web-delivery
#   footprint (COG + tiles) is a real reduction.
BANDWIDTH_REFERENCE["derived"] = {
    "web_reduction_factor": 64_900_000 / 19_519_859,     # 3.32×
    "product_reduction_factor": 64_900_000 / 168_119_859,  # 0.39×
    "input_at_1_mbps_s": 64_900_000 * 8 / 1_000_000,     # 519.2 s
    "web_at_1_mbps_s": 19_519_859 * 8 / 1_000_000,       # 156.2 s
    "output_at_1_mbps_s": 168_119_859 * 8 / 1_000_000,   # 1344.9 s
    "input_at_5_mbps_s": 64_900_000 * 8 / 5_000_000,     # 103.8 s
    "web_at_5_mbps_s": 19_519_859 * 8 / 5_000_000,       # 31.2 s
    "output_at_5_mbps_s": 168_119_859 * 8 / 5_000_000,   # 269.0 s
    "input_at_20_mbps_s": 64_900_000 * 8 / 20_000_000,   # 26.0 s
    "web_at_20_mbps_s": 19_519_859 * 8 / 20_000_000,     # 7.8 s
    "output_at_20_mbps_s": 168_119_859 * 8 / 20_000_000,  # 67.2 s
}

# ---- COG streaming write (measured separate from a full run) -----------------
# For a 7743×7748×4 GeoTIFF:
#   baseline RSS  52 MB, peak 665 MB, rise 613 MB  (pre-stream rewrite)
#   baseline RSS ~50 MB, peak 389 MB, rise ~340 MB  (post-stream rewrite, cap 128 MB)
COG_MEASUREMENT = {
    "source_geotiff_bytes": 149_600_000,
    "source_pixels": 7743 * 7748 * 4,   # 240 MB full-res reads would cost
    "output_cog_bytes": 9_800_000,
    "output_tiles": 24,
    "peak_rss_mb_pre": 665,   # before the stream rewrite of _write_cog
    "peak_rss_mb_post": 389,  # after: windowed read + capped GDAL cache
    "baseline_rss_mb": 52,
    "rise_mb_before": 613,
    "rise_mb_after": 337,
    "overviews": [2, 4, 8, 16],
    "internal_mask": True,
}
