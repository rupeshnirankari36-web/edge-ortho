"""Stable data contracts between EdgeOrtho pipeline stages.

The brief (GEOAI 01) requires modules to integrate through *documented schemas*
rather than private internal structures. Every dataclass here has a `to_dict`
that produces the JSON persisted into run records, reports and the API.

Nothing in this module invents data: fields are `None` when a measurement or
metadata value is genuinely unavailable.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Frame / ingest
# ---------------------------------------------------------------------------

RejectReason = Literal[
    "unreadable",
    "unsupported_format",
    "missing_gps",
    "invalid_gps",
    "gps_out_of_range",
    "zero_size",
    "decode_failed",
]

#: Human readable explanation for each rejection reason. Used both by the API
#: and by the UI so an operator is never shown a bare error code.
REJECT_REASON_TEXT: dict[str, str] = {
    "unreadable": "File could not be opened by the decoder.",
    "unsupported_format": "Extension is not a supported drone image format.",
    "missing_gps": "No latitude/longitude tags found in EXIF or XMP.",
    "invalid_gps": "Latitude/longitude tags exist but are unparseable or zeroed.",
    "gps_out_of_range": "Latitude/longitude outside valid WGS84 range.",
    "zero_size": "File is empty (0 bytes).",
    "decode_failed": "Metadata parsed but the pixel data could not be decoded.",
}

WarningCode = Literal[
    "missing_altitude",
    "missing_focal_length",
    "missing_sensor_width",
    "missing_yaw",
    "large_gps_jump",
    "below_expected_overlap",
    "not_nadir",
    "dataset_too_small",
    "single_strip",
]

WARNING_TEXT: dict[str, str] = {
    "missing_altitude": "No altitude tag: ground sampling distance cannot be estimated from this frame.",
    "missing_focal_length": "No 35mm-equivalent or physical focal length: GSD estimate unavailable.",
    "missing_sensor_width": "No sensor width metadata: physical GSD estimate unavailable.",
    "missing_yaw": "No camera yaw/heading tag: heading was derived from the GPS track instead.",
    "large_gps_jump": "Large gap in the GPS track: possible dropped frames during the flight.",
    "below_expected_overlap": "Estimated ground overlap is low; feature matching may fail for some pairs.",
    "not_nadir": "Gimbal pitch suggests a non-nadir capture; the 2D flat-ground assumption is weaker.",
    "dataset_too_small": "Fewer than 4 accepted frames: a mosaic cannot be composed.",
    "single_strip": "Flight path is a single strip: the output is a corridor map, not an area map.",
    "absolute_altitude_only": (
        "Altitude is above mean sea level with no above-ground reading: the ground sampling "
        "distance and metric scale are approximate."
    ),
    "no_geotagged_frames": "No discovered file carried usable GPS metadata.",
}


@dataclass
class FrameRecord:
    """One discovered image and every piece of metadata extracted from it."""

    frame_id: str
    path: str
    filename: str
    bytes: int
    accepted: bool

    # geometry / metadata (None == genuinely unavailable)
    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float | None = None
    altitude_source: str | None = None  # "exif_gps" | None
    yaw_deg: float | None = None
    yaw_source: str | None = None  # "exif" | "gps_track" | None

    width: int | None = None
    height: int | None = None
    make: str | None = None
    model: str | None = None
    focal_length_mm: float | None = None
    focal_length_35mm: float | None = None
    sensor_width_mm: float | None = None
    captured_at: str | None = None

    # derived (only when inputs exist)
    gsd_m: float | None = None
    gsd_source: str | None = None  # "35mm_equiv" | "sensor_width" | None
    footprint_w_m: float | None = None
    footprint_h_m: float | None = None
    projected_x: float | None = None  # easting (m) in run CRS
    projected_y: float | None = None  # northing (m) in run CRS

    reject_reason: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["reject_reason_text"] = REJECT_REASON_TEXT.get(self.reject_reason or "")
        d["warning_text"] = [WARNING_TEXT.get(w, w) for w in self.warnings]
        return d


@dataclass
class NeighbourRecord:
    """A candidate image pair selected from the projected GPS positions."""

    source_id: str
    target_id: str
    distance_m: float
    estimated_overlap: float | None = None
    selection: str = "gps_kdtree"  # "gps_kdtree" | "sequential_fallback"


TransformModel = Literal["affine", "similarity", "homography"]
PairStatus = Literal[
    "ok",
    "insufficient_keypoints",
    "insufficient_matches",
    "rejected_by_ransac",
    "degenerate_transform",
    "high_reprojection_error",
    "decode_failed",
]


@dataclass
class PairTransform:
    """Result of matching + robustly fitting one image pair."""

    source_id: str
    target_id: str
    model: str
    status: str
    matrix: list[list[float]] | None = None
    keypoints_source: int = 0
    keypoints_target: int = 0
    raw_matches: int = 0
    ratio_filtered_matches: int = 0
    inliers: int = 0
    inlier_ratio: float | None = None
    reprojection_error_px: float | None = None
    reprojection_error_m: float | None = None
    scale: float | None = None
    rotation_deg: float | None = None
    match_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GlobalPose:
    """Refined placement of a frame on the output canvas."""

    frame_id: str
    # pixel-space similarity: [scale, theta, tx, ty] mapping frame px -> canvas px
    scale: float
    theta_rad: float
    tx: float
    ty: float
    confidence: float
    seed_source: str  # "gps" | "chained" | "orphan"
    gps_error_px: float | None = None
    constraints_used: int = 0
    reprojection_error_px: float | None = None

    def matrix(self) -> list[list[float]]:
        c, s = math.cos(self.theta_rad) * self.scale, math.sin(self.theta_rad) * self.scale
        return [[c, -s, self.tx], [s, c, self.ty], [0.0, 0.0, 1.0]]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["matrix"] = self.matrix()
        return d


@dataclass
class OutputMetadata:
    """Everything a GIS user needs to judge the exported raster."""

    produced: bool = False
    kind: str = "preliminary_visual_mosaic"  # or "georeferenced_orthomosaic"
    crs: str | None = None
    crs_name: str | None = None
    transform: list[float] | None = None  # GDAL 6-tuple
    bounds: list[float] | None = None  # [minx, miny, maxx, maxy] in raster CRS
    bounds_wgs84: list[float] | None = None
    width: int | None = None
    height: int | None = None
    bands: int = 0
    gsd_m: float | None = None
    pixel_resolution_m: float | None = None
    nodata: float | None = None
    alpha_mask: bool = False
    geotiff_path: str | None = None
    geotiff_bytes: int | None = None
    cog_path: str | None = None
    cog_bytes: int | None = None
    cog_driver: str | None = None
    cog_messages: list[str] = field(default_factory=list)
    cog_validation: dict[str, Any] = field(default_factory=dict)
    cog_validation_failed: bool = False
    tiles_dir: str | None = None
    tile_count: int | None = None
    min_zoom: int | None = None
    max_zoom: int | None = None
    tiles_produced: bool = False
    tiles_messages: list[str] = field(default_factory=list)
    preview_png: str | None = None
    georeferencing_basis: str | None = None
    validation: dict[str, Any] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StageRecord:
    """One pipeline stage: what it did, how long it took, whether it worked."""

    name: str
    index: int
    status: str  # pending | running | done | skipped | failed
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_s: float | None = None
    detail: str | None = None
    error: str | None = None
    unsupported_reason: str | None = None
    counters: dict[str, Any] = field(default_factory=dict)
    rss_mb_at_end: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MetricsRecord:
    """Run-level resource + quality measurements (M4 evidence)."""

    run_id: str
    profile: str = "laptop"
    stage_metrics: list[dict[str, Any]] = field(default_factory=list)

    wall_clock_s: float | None = None
    time_to_first_tile_s: float | None = None
    peak_rss_mb: float | None = None
    baseline_rss_mb: float | None = None
    peak_rss_delta_mb: float | None = None
    avg_cpu_percent: float | None = None
    peak_cpu_percent: float | None = None
    cpu_cores_effective: int | None = None
    disk_read_bytes: int | None = None
    disk_write_bytes: int | None = None

    frames_total: int | None = None
    frames_accepted: int | None = None
    frames_rejected: int | None = None
    frames_failed: int | None = None
    frames_composed: int | None = None
    throughput_fps: float | None = None

    # settings that make runs comparable in the Performance Lab
    feature_detector: str | None = None
    alignment_model: str | None = None
    matching_megapixels: float | None = None
    tile_size: int | None = None
    output_crs: str | None = None
    output_kind: str | None = None

    input_bytes: int | None = None
    output_bytes: int | None = None
    reduction_factor: float | None = None

    pairs_candidates: int | None = None
    pairs_matched: int | None = None
    pairs_failed: int | None = None
    total_matches: int | None = None
    total_inliers: int | None = None
    mean_inlier_ratio: float | None = None
    mean_reprojection_error_px: float | None = None
    mean_gps_placement_error_m: float | None = None

    profile_limit_cores: int | None = None
    profile_limit_ram_mb: int | None = None
    profile_enforcement: dict[str, Any] = field(default_factory=dict)

    bandwidth: dict[str, Any] = field(default_factory=dict)
    measurements_unavailable: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Bandwidth maths (brief: transfer_seconds = bytes * 8 / bits_per_second)
# ---------------------------------------------------------------------------

BANDWIDTH_TEST_MBPS: tuple[int, ...] = (1, 5, 20)


def transfer_seconds(n_bytes: int, bits_per_second: float) -> float:
    """Exact formula from the brief: bytes x 8 / bits per second."""
    if bits_per_second <= 0:
        raise ValueError("bits_per_second must be positive")
    return (n_bytes * 8.0) / bits_per_second


def bandwidth_table(
    input_bytes: int | None,
    output_bytes: int | None,
    web_bytes: int | None = None,
) -> dict[str, Any]:
    """Transfer time for raw input and output products at 1, 5 and 20 Mbps.

    Three quantities are measured, not estimated:

    * ``input_bytes`` - the raw frames, which a cloud workflow would upload;
    * ``output_bytes`` - everything this run wrote, which includes the lossless
      GeoTIFF and is therefore often *larger* than the input;
    * ``web_bytes`` - only what a browser actually needs (COG + XYZ tiles).

    No saving is claimed where there is none: the delta is reported per series and
    negative deltas are printed as negative. If a byte count is unavailable the
    corresponding entry stays ``None`` rather than being filled with an estimate.
    """
    table: dict[str, Any] = {
        "formula": "transfer_seconds = bytes * 8 / bits_per_second",
        "input_bytes": input_bytes,
        "output_bytes": output_bytes,
        "web_bytes": web_bytes,
        "reduction_factor": None,
        "web_reduction_factor": None,
        "scenarios": {},
    }
    if input_bytes is not None and output_bytes not in (None, 0):
        table["reduction_factor"] = input_bytes / float(output_bytes)
    if input_bytes is not None and web_bytes not in (None, 0):
        table["web_reduction_factor"] = input_bytes / float(web_bytes)

    per_scenario: dict[str, Any] = {}
    for mbps in BANDWIDTH_TEST_MBPS:
        bps = mbps * 1_000_000.0
        entry: dict[str, Any] = {"mbps": mbps}
        if input_bytes is not None:
            sec = transfer_seconds(input_bytes, bps)
            entry["input_seconds"] = sec
            entry["input_human"] = human_duration(sec)
        else:
            entry["input_seconds"] = None
            entry["input_human"] = None
        if output_bytes is not None:
            sec = transfer_seconds(output_bytes, bps)
            entry["output_seconds"] = sec
            entry["output_human"] = human_duration(sec)
        else:
            entry["output_seconds"] = None
            entry["output_human"] = None
        if web_bytes is not None:
            sec = transfer_seconds(web_bytes, bps)
            entry["web_seconds"] = sec
            entry["web_human"] = human_duration(sec)
        else:
            entry["web_seconds"] = None
            entry["web_human"] = None
        if entry["input_seconds"] is not None and entry["output_seconds"] is not None:
            entry["saved_seconds"] = entry["input_seconds"] - entry["output_seconds"]
            entry["saved_human"] = human_duration(entry["saved_seconds"])
        else:
            entry["saved_seconds"] = None
            entry["saved_human"] = None
        if entry["input_seconds"] is not None and entry["web_seconds"] is not None:
            entry["web_saved_seconds"] = entry["input_seconds"] - entry["web_seconds"]
            entry["web_saved_human"] = human_duration(entry["web_saved_seconds"])
        else:
            entry["web_saved_seconds"] = None
            entry["web_saved_human"] = None
        per_scenario[str(mbps)] = entry
    table["scenarios"] = per_scenario
    return table


def human_duration(seconds: float | None) -> str | None:
    """Human text for a duration, keeping the sign for negative deltas."""
    if seconds is None:
        return None
    if seconds < 0:
        # A negative delta is real information (the products are larger than the
        # input), so it keeps its sign instead of being rendered as "-0 ms".
        return f"-{human_duration(-seconds)}"
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {rem:.0f}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(minutes)}m"


def human_bytes(n: int | None) -> str | None:
    if n is None:
        return None
    step = 1024.0
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < step:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= step
    return f"{value:.1f} PB"
