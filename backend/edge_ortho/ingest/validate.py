"""Milestone 1 - ingestion and validation.

Produces the accepted/rejected metadata report required by the brief:

* every usable frame must have latitude and longitude, otherwise it is rejected
  and the reason is recorded;
* flight metadata (altitude, yaw, gimbal pitch) is reported when present and
  flagged as missing when not;
* the projected flight path is built here so the map viewer can draw real
  footprints;
* dataset-level suitability warnings (single strip, sparse overlap, hilly
  proxies) are surfaced rather than hidden.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from ..contracts import WARNING_TEXT, FrameRecord
from ..geo.projection import Projector, gsd_from_metadata
from .discovery import DiscoveryResult, discover_images
from .exif import ImageMetadata, is_nadir, read_image_metadata

#: Consecutive GPS steps larger than this multiple of the median step are
#: reported as a possible dropped frame in the flight track.
GPS_JUMP_FACTOR = 3.0


@dataclass
class IngestResult:
    discovery: DiscoveryResult
    frames: list[FrameRecord] = field(default_factory=list)
    projector: Projector | None = None
    crs_name: str | None = None
    summary: dict = field(default_factory=dict)
    dataset_warnings: list[dict] = field(default_factory=list)
    suitable: bool = False
    unsuitability_reasons: list[str] = field(default_factory=list)
    input_bytes: int = 0

    @property
    def accepted(self) -> list[FrameRecord]:
        return [f for f in self.frames if f.accepted]

    @property
    def rejected(self) -> list[FrameRecord]:
        return [f for f in self.frames if not f.accepted]

    def to_dict(self) -> dict:
        return {
            "discovery": self.discovery.to_dict(),
            "crs": self.crs_name,
            "summary": self.summary,
            "dataset_warnings": self.dataset_warnings,
            "suitable": self.suitable,
            "unsuitability_reasons": self.unsuitability_reasons,
            "input_bytes": self.input_bytes,
            "frames": [f.to_dict() for f in self.frames],
        }


def _normalise_angle_deg(a: float) -> float:
    return a % 360.0


def _bearing_deg(dx: float, dy: float) -> float:
    """Compass bearing (0 = north, clockwise) of a projected delta."""
    return _normalise_angle_deg(math.degrees(math.atan2(dx, dy)))


def _estimate_heading_from_track(frames: list[FrameRecord]) -> dict[str, float]:
    """Derive per-frame heading from the projected GPS track.

    This is a documented *fallback* used only when a frame has no yaw tag. It is
    recorded in ``FrameRecord.yaw_source`` as ``gps_track`` so the UI never
    presents a derived heading as a measured camera yaw.
    """
    pts = [(f.projected_x, f.projected_y) for f in frames]
    headings: dict[str, float] = {}
    n = len(frames)
    for i in range(n):
        if i == 0:
            ax, ay = pts[0]
            bx, by = pts[1]
        elif i == n - 1:
            ax, ay = pts[n - 2]
            bx, by = pts[n - 1]
        else:
            ax, ay = pts[i - 1]
            bx, by = pts[i + 1]
        dx, dy = bx - ax, by - ay
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            continue
        headings[frames[i].frame_id] = _bearing_deg(dx, dy)
    return headings


def ingest(
    source: str | Path | list[str | Path],
    recursive: bool = True,
    discover: DiscoveryResult | None = None,
) -> IngestResult:
    """Ingest one folder (or an explicit file list) into validated FrameRecords."""
    if discover is None:
        if isinstance(source, (list, tuple)):
            disc = DiscoveryResult(root=None)
            for item in source:
                sub = discover_images(item, recursive=recursive)
                disc.images.extend(sub.images)
                disc.skipped_unsupported.extend(sub.skipped_unsupported)
                disc.missing.extend(sub.missing)
            disc.images = sorted(set(disc.images))
            discover = disc
        else:
            discover = discover_images(source, recursive=recursive)

    result = IngestResult(discovery=discover)
    frames: list[FrameRecord] = []

    for idx, path in enumerate(discover.images):
        frame_id = path.stem if path.stem else f"frame_{idx:04d}"
        # Guarantee unique ids when a folder contains repeated stems.
        existing = {f.frame_id for f in frames}
        if frame_id in existing:
            frame_id = f"{frame_id}_{idx:04d}"

        try:
            nbytes = path.stat().st_size
        except OSError:
            nbytes = 0
        result.input_bytes += nbytes

        meta = read_image_metadata(path)
        record = _build_record(frame_id, path, nbytes, meta)
        frames.append(record)

    # --- projection + derived geometry ------------------------------------
    accepted = [f for f in frames if f.accepted]
    if accepted:
        lon0 = statistics.fmean(f.longitude for f in accepted)
        lat0 = statistics.fmean(f.latitude for f in accepted)
        projector = Projector.for_points(lon0, lat0)
        result.projector = projector
        result.crs_name = projector.crs_name()
        for f in accepted:
            f.projected_x, f.projected_y = projector.project(f.longitude, f.latitude)

    # --- heading fallback --------------------------------------------------
    if len(accepted) >= 3:
        missing_yaw = [f for f in accepted if f.yaw_deg is None]
        if missing_yaw:
            headings = _estimate_heading_from_track(accepted)
            for f in missing_yaw:
                if f.frame_id in headings:
                    f.yaw_deg = headings[f.frame_id]
                    f.yaw_source = "gps_track"
                    if "missing_yaw" not in f.warnings:
                        f.warnings.append("missing_yaw")

    # --- dataset level checks ---------------------------------------------
    _apply_dataset_warnings(result, accepted)

    result.frames = frames
    result.summary = _build_summary(result)
    return result


def _build_record(frame_id: str, path: Path, nbytes: int, meta: ImageMetadata) -> FrameRecord:
    rec = FrameRecord(
        frame_id=frame_id,
        path=str(path),
        filename=path.name,
        bytes=nbytes,
        accepted=False,
    )
    rec.width = meta.width
    rec.height = meta.height
    rec.make = meta.make
    rec.model = meta.model
    rec.focal_length_mm = meta.focal_length_mm
    rec.focal_length_35mm = meta.focal_length_35mm
    rec.sensor_width_mm = meta.sensor_width_mm
    rec.captured_at = meta.captured_at
    rec.latitude = meta.latitude
    rec.longitude = meta.longitude
    rec.altitude_m = meta.altitude_m
    rec.altitude_source = meta.altitude_source
    rec.yaw_deg = meta.yaw_deg
    rec.yaw_source = meta.yaw_source
    rec.warnings = list(meta.warnings)

    if meta.error_code:
        rec.reject_reason = meta.error_code
        return rec

    if path.suffix.lower() not in (".jpg", ".jpeg", ".tif", ".tiff"):
        rec.reject_reason = "unsupported_format"
        return rec

    if meta.latitude is None or meta.longitude is None:
        rec.reject_reason = "missing_gps"
        return rec

    if not (-90.0 <= meta.latitude <= 90.0) or not (-180.0 <= meta.longitude <= 180.0):
        rec.reject_reason = "gps_out_of_range"
        return rec

    if meta.latitude == 0.0 and meta.longitude == 0.0:
        # Null island: the tag exists but carries no position.
        rec.reject_reason = "invalid_gps"
        return rec

    if rec.width is None or rec.height is None:
        rec.reject_reason = "decode_failed"
        return rec

    # --- geometry ---------------------------------------------------------
    rec.gsd_m, rec.gsd_source = gsd_from_metadata(
        meta.altitude_m,
        rec.width,
        meta.focal_length_mm,
        meta.focal_length_35mm,
        meta.sensor_width_mm,
    )
    if rec.gsd_m and rec.gsd_m > 0:
        rec.footprint_w_m = rec.width * rec.gsd_m
        rec.footprint_h_m = rec.height * rec.gsd_m

    nadir = is_nadir(meta.pitch_deg)
    if nadir is False:
        rec.warnings.append("not_nadir")
    if meta.altitude_m is None:
        rec.warnings.append("missing_altitude")
    if meta.focal_length_mm is None and meta.focal_length_35mm is None:
        rec.warnings.append("missing_focal_length")
    if rec.sensor_width_mm is None:
        rec.warnings.append("missing_sensor_width")

    rec.accepted = True
    return rec


def _apply_dataset_warnings(result: IngestResult, accepted: list[FrameRecord]) -> None:
    warnings: list[dict] = []
    reasons: list[str] = []

    def add(code: str, detail: str) -> None:
        warnings.append({"code": code, "text": WARNING_TEXT.get(code, code), "detail": detail})

    if not accepted:
        # Silence here would be the worst outcome: the run is refused, so the reason
        # has to be stated in the report the user actually reads.
        add(
            "no_geotagged_frames",
            "No discovered file carried usable GPS coordinates, altitude and a readable image.",
        )
        reasons.append("no file carried usable GPS metadata, so nothing could be placed on the ground")
    elif len(accepted) < 4:
        add("dataset_too_small", f"{len(accepted)} accepted frame(s); at least 4 are needed.")
        reasons.append(
            f"only {len(accepted)} geotagged frame(s) passed validation; at least 4 are required "
            "before a mosaic can be attempted"
        )

    absolute_only = [f for f in accepted if "absolute_altitude_only" in (f.warnings or [])]
    if absolute_only and len(absolute_only) == len(accepted):
        add(
            "absolute_altitude_only",
            "Altitudes are above mean sea level with no above-ground reading, so ground sampling "
            "distance is approximate and the metric scale should be treated as provisional.",
        )
        reasons.append(
            "no above-ground altitude tag was found; the metric scale derived from altitude is "
            "provisional"
        )

    if len(accepted) >= 3:
        pts = [(f.projected_x, f.projected_y) for f in accepted]
        # --- single strip detection (PCA on the flight path) --------------
        mx = statistics.fmean(p[0] for p in pts)
        my = statistics.fmean(p[1] for p in pts)
        sxx = sum((p[0] - mx) ** 2 for p in pts) / len(pts)
        syy = sum((p[1] - my) ** 2 for p in pts) / len(pts)
        sxy = sum((p[0] - mx) * (p[1] - my) for p in pts) / len(pts)
        trace = sxx + syy
        det = sxx * syy - sxy * sxy
        disc = max(0.0, (trace / 2) ** 2 - det)
        l1 = trace / 2 + math.sqrt(disc)
        l2 = max(1e-9, trace / 2 - math.sqrt(disc))
        if l2 > 0 and (l1 / l2) > 12.0 and l1 > 0:
            add(
                "single_strip",
                f"track aspect ratio {l1 / l2:.0f}:1 - output will be a corridor map.",
            )

        # --- GPS jumps ----------------------------------------------------
        steps = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        if steps:
            median_step = statistics.median(steps)
            if median_step > 0:
                big = [s for s in steps if s > GPS_JUMP_FACTOR * median_step]
                if big:
                    add(
                        "large_gps_jump",
                        f"{len(big)} step(s) exceed {GPS_JUMP_FACTOR:g}x the median spacing "
                        f"({median_step:.1f} m), largest {max(big):.1f} m.",
                    )

        # --- overlap sanity ----------------------------------------------
        gsds = [f.gsd_m for f in accepted if f.gsd_m]
        median_step = statistics.median(
            [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)] or [0.0]
        )
        if gsds and median_step > 0:
            footprint = statistics.median(
                [f.footprint_h_m for f in accepted if f.footprint_h_m] or [0.0]
            )
            if footprint and median_step > 0.6 * footprint:
                add(
                    "below_expected_overlap",
                    f"median frame spacing {median_step:.1f} m is {median_step / footprint:.0%} "
                    f"of the {footprint:.1f} m along-track footprint.",
                )

    pitch_seen = any(f.warnings and "not_nadir" in f.warnings for f in accepted)
    if pitch_seen:
        reasons.append("non-nadir capture detected; 2D flat-ground assumption weakened")

    result.dataset_warnings = warnings
    result.unsuitability_reasons = reasons
    result.suitable = len(accepted) >= 4


def _build_summary(result: IngestResult) -> dict:
    accepted = result.accepted
    rejected = result.rejected
    by_reason: dict[str, int] = {}
    for f in rejected:
        by_reason[f.reject_reason or "unknown"] = by_reason.get(f.reject_reason or "unknown", 0) + 1

    gsds = [f.gsd_m for f in accepted if f.gsd_m]
    alts = [f.altitude_m for f in accepted if f.altitude_m is not None]
    yaws = [f.yaw_deg for f in accepted if f.yaw_deg is not None]
    pixels = sum((f.width or 0) * (f.height or 0) for f in accepted)

    extent = None
    if accepted:
        xs = [f.projected_x for f in accepted]
        ys = [f.projected_y for f in accepted]
        extent = {
            "easting_m": [min(xs), max(xs)],
            "northing_m": [min(ys), max(ys)],
            "width_m": max(xs) - min(xs),
            "height_m": max(ys) - min(ys),
        }

    return {
        "frames_discovered": len(result.discovery.images),
        "frames_accepted": len(accepted),
        "frames_rejected": len(rejected),
        "rejected_by_reason": by_reason,
        "unsupported_files_skipped": len(result.discovery.skipped_unsupported),
        "total_bytes": result.input_bytes,
        "total_megapixels": pixels / 1e6,
        "gps_available": len(accepted) > 0,
        "altitude_available": len(alts) > 0,
        "altitude_range_m": [min(alts), max(alts)] if alts else None,
        "altitude_source": next((f.altitude_source for f in accepted if f.altitude_source), None),
        "yaw_available": len(yaws) == len(accepted) and len(yaws) > 0,
        "yaw_source": next((f.yaw_source for f in accepted if f.yaw_source), None),
        "gsd_available": len(gsds) > 0,
        "gsd_m": statistics.median(gsds) if gsds else None,
        "gsd_source": next((f.gsd_source for f in accepted if f.gsd_source), None),
        "footprint_m": (
            statistics.median([f.footprint_w_m for f in accepted if f.footprint_w_m])
            if any(f.footprint_w_m for f in accepted)
            else None
        ),
        "image_dimensions": sorted(
            {f"{f.width}x{f.height}" for f in accepted if f.width and f.height}
        ),
        "camera_models": sorted({(f.model or "unknown").strip() for f in accepted}),
        "flight_extent": extent,
        "capture_window": _capture_window(accepted),
    }


def _capture_window(frames: list[FrameRecord]) -> dict | None:
    stamps = sorted(f.captured_at for f in frames if f.captured_at)
    if not stamps:
        return None
    return {"first": stamps[0], "last": stamps[-1]}
