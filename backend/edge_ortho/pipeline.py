"""The EdgeOrtho pipeline orchestrator.

    Ingest -> Validate GPS -> Plan Neighbours -> Match Features -> Align
    -> Compose Tiles -> Georeference -> Export

Each stage reports a real status (``done`` / ``skipped`` / ``failed``) plus
counters, timing and error text. A stage that cannot run because the data or the
tooling does not support it is marked ``skipped`` with an ``unsupported_reason``
rather than being reported as successful.

Output is intentionally conservative about accuracy:

* the exported raster is labelled ``georeferenced_orthomosaic`` only when a CRS
  and a metadata-supported pixel size are actually available;
* ``gps_placement_error`` is always described as a consistency check against
  camera GPS tags, never as ground-control accuracy;
* the mosaic is never described as survey grade.
"""

from __future__ import annotations

import csv
import json
import statistics
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from . import config
from .align.global_align import (
    anchor_to_gps,
    chain_homography_poses,
    compare_alignment_paths,
    define_canvas,
    filter_pairs_by_seed_consistency,
    recompute_gps_stats,
    resolve_heading_convention,
    seed_poses,
    solve_global_alignment,
)
from .align.transform import estimate_pair_transform
from .compose.mosaic import compose_mosaic, estimate_exposure_gains
from .contracts import (
    MetricsRecord,
    OutputMetadata,
    StageRecord,
    bandwidth_table,
    human_bytes,
)
from .features.matching import (
    create_detector,
    detect_features,
    match_descriptors,
    matching_scale,
)
from .geo import raster as geopraster
from .ingest.validate import ingest
from .monitor.resources import MemoryCeilingExceeded, MemoryGuard, ResourceSampler, stage_timer
from .plan.neighbours import plan_neighbours
from .profiles import ResourceLimiter, get_profile

STAGES: tuple[tuple[str, str], ...] = (
    ("ingest", "Ingest"),
    ("validate_gps", "Validate GPS"),
    ("plan_neighbours", "Plan Neighbours"),
    ("match_features", "Match Features"),
    ("align", "Align"),
    ("compose_tiles", "Compose Tiles"),
    ("georeference", "Georeference"),
    ("export", "Export"),
)

Emitter = Callable[[dict], None]


def _noop(_event: dict) -> None:  # pragma: no cover
    return None


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class PipelineRun:
    def __init__(
        self,
        run_id: str,
        name: str,
        source: str | list[str],
        settings: config.PipelineSettings | None = None,
        emit: Emitter | None = None,
    ):
        self.run_id = run_id
        self.name = name
        self.source = source
        self.settings = settings or config.PipelineSettings()
        self.emit = emit or _noop
        self.out_dir = config.run_output_dir(run_id)
        self.meta_dir = config.run_meta_path(run_id)
        self.stages: list[StageRecord] = [
            StageRecord(name=key, index=i, status="pending", detail=label)
            for i, (key, label) in enumerate(STAGES)
        ]
        self.started_at = utcnow()
        self.t0 = time.perf_counter()
        self.sampler = ResourceSampler()
        self.messages: list[str] = []
        self.limitations: list[str] = []
        self.artifacts: list[dict] = []
        self.report: dict[str, Any] = {}
        self.frames_failed_during_run = 0
        self._alignment_comparison: dict = {}
        self.output: OutputMetadata | None = None
        self.geotiff_result = None
        self.preview_meta: dict = {}

    # -- helpers ----------------------------------------------------------
    def _stage(self, key: str) -> StageRecord:
        for s in self.stages:
            if s.name == key:
                return s
        raise KeyError(key)

    def _start(self, key: str) -> None:
        s = self._stage(key)
        s.status = "running"
        s.started_at = utcnow()
        self.emit({"type": "stage", "stage": s.to_dict()})

    def _finish(
        self,
        key: str,
        elapsed: float,
        counters: dict | None = None,
        detail: str | None = None,
    ) -> None:
        s = self._stage(key)
        s.status = "done"
        s.finished_at = utcnow()
        s.elapsed_s = elapsed
        s.rss_mb_at_end = self.sampler.rss_mb()
        if counters:
            s.counters = counters
        if detail:
            s.detail = detail
        self.emit({"type": "stage", "stage": s.to_dict(), "metrics": self._live_metrics()})

    def _skip(self, key: str, reason: str, elapsed: float = 0.0) -> None:
        s = self._stage(key)
        s.status = "skipped"
        s.finished_at = utcnow()
        s.elapsed_s = elapsed
        s.unsupported_reason = reason
        self.emit({"type": "stage", "stage": s.to_dict()})

    def _fail(self, key: str, error: str, elapsed: float = 0.0) -> None:
        s = self._stage(key)
        s.status = "failed"
        s.finished_at = utcnow()
        s.elapsed_s = elapsed
        s.error = error
        self.emit({"type": "stage", "stage": s.to_dict()})

    def _live_metrics(self) -> dict:
        return {
            "elapsed_s": time.perf_counter() - self.t0,
            "rss_mb": self.sampler.rss_mb(),
            "peak_rss_mb": self.sampler.peak_rss_mb,
            "baseline_rss_mb": self.sampler.baseline_rss_mb,
        }

    def _add_artifact(self, kind: str, path: Path | str | None, label: str, extra: dict | None = None) -> None:
        if path is None:
            return
        path = Path(path)
        entry = {
            "kind": kind,
            "label": label,
            "path": str(path),
            "filename": path.name,
            "bytes": path.stat().st_size if path.exists() else None,
        }
        if extra:
            entry.update(extra)
        self.artifacts.append(entry)

    # -- main -------------------------------------------------------------
    def run(self) -> dict:
        profile = get_profile(self.settings.profile)
        limiter = ResourceLimiter(profile)
        enforcement = limiter.apply()
        guard = MemoryGuard(profile.ram_limit_mb, self.sampler, profile.name)
        self.sampler.start()
        self.emit({"type": "started", "run_id": self.run_id, "stages": [s.to_dict() for s in self.stages]})

        status = "succeeded"
        error: str | None = None
        ingest_result = None
        plan = None
        pairs: list = []
        canvas = None
        poses: dict = {}
        output = OutputMetadata()
        query_total = 0
        matched_total = 0

        try:
            # ---- 1. Ingest ------------------------------------------------
            self._start("ingest")
            with stage_timer() as t:
                ingest_result = ingest(self.source)
            if not ingest_result.discovery.images:
                self._fail("ingest", "no supported image files were found at the source")
                raise PipelineStopped("no supported image files were found")
            query_total = len(ingest_result.discovery.images)
            self._finish(
                "ingest",
                t["elapsed_s"],
                {
                    "files_discovered": len(ingest_result.discovery.images),
                    "unsupported_skipped": len(ingest_result.discovery.skipped_unsupported),
                    "input_bytes": ingest_result.input_bytes,
                },
                detail=f"{len(ingest_result.discovery.images)} candidate file(s) discovered",
            )

            # ---- 2. Validate GPS -----------------------------------------
            self._start("validate_gps")
            with stage_timer() as t:
                summary = ingest_result.summary
                report_path = self.meta_dir / "metadata_report.json"
                report_path.write_text(
                    json.dumps(ingest_result.to_dict(), indent=2), encoding="utf-8"
                )
                csv_path = self.meta_dir / "frames.csv"
                _write_frames_csv(csv_path, ingest_result)
            self._add_artifact("metadata_json", report_path, "Metadata validation report")
            self._add_artifact("frames_csv", csv_path, "Frame metadata table")
            accepted = ingest_result.accepted
            rejected = ingest_result.rejected
            self._finish(
                "validate_gps",
                t["elapsed_s"],
                {
                    "accepted": len(accepted),
                    "rejected": len(rejected),
                    "rejected_by_reason": summary.get("rejected_by_reason", {}),
                    "crs": ingest_result.crs_name,
                    "gsd_m": summary.get("gsd_m"),
                    "gsd_source": summary.get("gsd_source"),
                    "gps_available": summary.get("gps_available"),
                },
                detail=(
                    f"{len(accepted)} accepted, {len(rejected)} rejected"
                    + (f"; CRS {ingest_result.crs_name}" if ingest_result.crs_name else "")
                ),
            )
            for w in ingest_result.dataset_warnings:
                self.messages.append(f"{w['code']}: {w['detail']}")
            if not accepted:
                self._skip("plan_neighbours", "no geotagged frames survived validation")
                self._skip("match_features", "no accepted frames")
                self._skip("align", "no accepted frames")
                self._skip("compose_tiles", "no accepted frames")
                self._skip("georeference", "no accepted frames")
                self._skip("export", "no accepted frames")
                raise PipelineStopped("no geotagged frames survived validation")

            if len(accepted) < self.settings.min_valid_frames:
                self._skip(
                    "plan_neighbours",
                    f"only {len(accepted)} accepted frame(s); at least "
                    f"{self.settings.min_valid_frames} are required for a mosaic",
                )
                self._skip("match_features", "dataset below the minimum frame count")
                self._skip("align", "dataset below the minimum frame count")
                self._skip("compose_tiles", "dataset below the minimum frame count")
                self._skip("georeference", "dataset below the minimum frame count")
                self._skip("export", "dataset below the minimum frame count")
                raise PipelineStopped(
                    f"dataset has {len(accepted)} usable frame(s); at least "
                    f"{self.settings.min_valid_frames} geotagged frames are needed"
                )

            # ---- 3. Plan neighbours --------------------------------------
            self._start("plan_neighbours")
            with stage_timer() as t:
                plan = plan_neighbours(
                    accepted,
                    radius_factor=self.settings.neighbour_radius_factor,
                    max_links=self.settings.neighbour_max_links,
                    min_overlap=self.settings.min_estimated_overlap,
                )
            self._finish(
                "plan_neighbours",
                t["elapsed_s"],
                {
                    "candidate_pairs": len(plan.neighbours),
                    "all_pairs_possible": plan.all_pairs_possible,
                    "reduction_factor": plan.reduction_factor,
                    "radius_m": plan.radius_m,
                    "selection_method": plan.selection_method,
                    "pairs_below_overlap": plan.pairs_below_overlap,
                },
                detail=(
                    f"{len(plan.neighbours)} candidate pair(s) from "
                    f"{plan.all_pairs_possible} possible"
                    + (f"; {plan.reduction_factor:.1f}x fewer" if plan.reduction_factor else "")
                ),
            )
            self.messages.extend(plan.notes)
            if not plan.neighbours:
                self._skip("match_features", "the neighbour graph is empty")
                self._skip("align", "no candidate pairs to align")
                self._skip("compose_tiles", "no validated pairwise alignment")
                self._skip("georeference", "no validated pairwise alignment")
                self._skip("export", "no output to export")
                raise PipelineStopped("no candidate image pairs: the flight path or overlap is unsuitable")

            # ---- 4. Match features ---------------------------------------
            self._start("match_features")
            detector = create_detector(self.settings.feature_detector, self.settings.orb_features)
            with stage_timer() as t:
                pairs, match_stats = self._match_stage(accepted, plan.neighbours, detector)
            matched_total = int(match_stats["pairs_ok"])
            self._finish(
                "match_features",
                t["elapsed_s"],
                match_stats,
                detail=(
                    f"{match_stats['pairs_ok']}/{match_stats['pairs_attempted']} pairs aligned; "
                    f"{match_stats['total_inliers']} RANSAC inliers"
                ),
            )
            if not pairs:
                self._skip("align", "no pair passed matching and RANSAC validation")
                self._skip("compose_tiles", "no validated pairwise alignment")
                self._skip("georeference", "no validated pairwise alignment")
                self._skip("export", "no output to export")
                raise PipelineStopped(
                    "no image pair produced a validated transform: overlap or texture is unsuitable"
                )

            # ---- 5. Align ------------------------------------------------
            self._start("align")
            with stage_timer() as t:
                alignment = self._align_stage(accepted, ingest_result, pairs)
                canvas = alignment["canvas"]
                poses = alignment["poses"]
                self._alignment_comparison = alignment.get("comparison", {})
            self._finish(
                "align",
                t["elapsed_s"],
                {
                    "heading_convention": alignment["heading"]["selected"],
                    "heading_offset_deg": alignment["heading"]["heading_offset_deg"],
                    "constraints": alignment["solver"].get("constraints"),
                    "correspondences": alignment["solver"].get("correspondences"),
                    "residual_rmse_px": alignment["residuals"].get("rmse_px"),
                    "residual_rmse_m": alignment["residuals"].get("rmse_m"),
                    "gps_placement_error_mean_m": alignment["gps_after"]["mean"],
                    "canvas_px": [canvas.width, canvas.height] if canvas else None,
                    "output_gsd_m": canvas.gsd_m if canvas else None,
                    "homography_pairs_ok": alignment["homography_ok"],
                },
                detail=(
                    f"residual {alignment['residuals'].get('rmse_m', float('nan')):.2f} m; "
                    f"GPS consistency {alignment['gps_after']['mean']:.2f} m"
                    if alignment["residuals"].get("rmse_m") is not None
                    else "alignment solved"
                ),
            )
            self.messages.append(alignment["heading"]["note"])
            if canvas and canvas.cap_message:
                self.messages.append(canvas.cap_message)

            # ---- 6. Compose tiles ----------------------------------------
            if canvas is None or not canvas.georeferenced:
                self._skip(
                    "compose_tiles",
                    "no altitude/focal metadata, so a metric output grid cannot be defined; "
                    "EdgeOrtho will not invent a ground sampling distance",
                )
                self.limitations.append(
                    "Composition skipped: the dataset has no usable altitude or focal length, so no "
                    "metric ground sampling distance could be derived."
                )
            else:
                self._start("compose_tiles")
                with stage_timer() as t:
                    comp = self._compose_stage(accepted, poses, canvas, guard)
                self.geotiff_result = comp.pop("_raster")
                preview = comp.pop("_preview")
                self.preview_meta = preview
                self._add_artifact(
                    "raster", self.geotiff_result.path if self.geotiff_result else None,
                    "GeoTIFF output", {"crs": self.geotiff_result.crs if self.geotiff_result else None},
                )
                self._finish(
                    "compose_tiles",
                    t["elapsed_s"],
                    comp,
                    detail=(
                        f"{comp['tiles_written']}/{comp['tiles_total']} tile(s) written; "
                        f"first tile at "
                        f"{comp['time_to_first_tile_s']:.2f}s"
                        if comp.get("time_to_first_tile_s") is not None
                        else f"{comp['tiles_written']} tile(s) written"
                    ),
                )

        except MemoryCeilingExceeded as exc:
            status = "failed"
            error = str(exc)
            self._fail(self._first_running_stage(), str(exc))
            self.limitations.append(
                f"Run aborted by the {profile.name} RAM ceiling. This is a configured soft limit, "
                "not a physical Raspberry Pi or Jetson measurement."
            )
        except PipelineStopped as exc:
            status = "failed"
            error = str(exc)
        except Exception as exc:  # pragma: no cover - defensive
            status = "failed"
            error = f"{type(exc).__name__}: {exc}"
            self._fail(self._first_running_stage(), error)
            self.messages.append("Traceback: " + traceback.format_exc(limit=6))

        # ---- 7/8 Georeference + Export ----------------------------------
        try:
            if status == "succeeded" and canvas is not None and poses:
                self._georeference_and_export(canvas, poses, output, ingest_result)
        except Exception as exc:  # pragma: no cover - defensive
            self.messages.append(f"georeference/export error: {exc}")

        # ---- finalise ----------------------------------------------------
        self.sampler.stop()
        wall = time.perf_counter() - self.t0
        metrics = self._build_metrics(
            status, wall, ingest_result, plan, pairs, canvas, output, profile, enforcement,
            guard, query_total, matched_total,
        )
        self.report = self._build_report(
            status, error, ingest_result, plan, canvas, output, metrics, enforcement, guard
        )
        self_report_path = self.meta_dir / "report.json"
        self_report_path.write_text(json.dumps(self.report, indent=2), encoding="utf-8")
        self._add_artifact("report_json", self_report_path, "Run report (JSON)")
        csv_metrics = self.meta_dir / "metrics.csv"
        _write_metrics_csv(csv_metrics, metrics)
        self._add_artifact("metrics_csv", csv_metrics, "Metrics (CSV)")
        self.report["artifacts"] = self.artifacts
        self._emit_final(status)
        limiter.restore()
        return self.report

    def _first_running_stage(self) -> str:
        for s in self.stages:
            if s.status == "running":
                return s.name
        for s in self.stages:
            if s.status == "pending":
                return s.name
        return STAGES[-1][0]

    # -- stage 4 ----------------------------------------------------------
    def _match_stage(self, frames, neighbours, detector):
        s = self.settings
        feats: dict[str, Any] = {}
        decodes_failed = 0
        for i, f in enumerate(frames):
            scale = matching_scale(f.width or 0, f.height or 0, s.matching_megapixels)
            feat = detect_features(f.path, f.frame_id, scale, detector, s.feature_detector)
            if feat.error:
                decodes_failed += 1
            feats[f.frame_id] = feat
            self.emit(
                {
                    "type": "progress",
                    "stage": "match_features",
                    "done": i + 1,
                    "total": len(frames),
                    "label": "detecting features",
                    "metrics": self._live_metrics(),
                }
            )

        pairs = []
        status_counts: dict[str, int] = {}
        total_inliers = 0
        total_matches = 0
        ratios: list[float] = []
        reproj: list[float] = []
        frame_lookup = by_id(frames)
        t_match = time.perf_counter()
        for i, n in enumerate(neighbours):
            a, b = feats.get(n.source_id), feats.get(n.target_id)
            if a is None or b is None:
                continue
            src_frame = frame_lookup.get(n.source_id)
            mr = match_descriptors(
                a, b,
                ratio_threshold=s.ratio_threshold,
                min_matches=s.min_matches,
                detector_name=s.feature_detector,
            )
            pt, geo = estimate_pair_transform(
                a, b, mr,
                model="affine",
                ransac_threshold_px=s.ransac_threshold_px,
                ransac_confidence=s.ransac_confidence,
                ransac_max_iters=s.ransac_max_iters,
                min_inliers=s.min_inliers,
                max_reprojection_error_px=s.max_reprojection_error_px,
                gsd_m=(src_frame.gsd_m if src_frame else None),
            )
            pairs.append((pt, geo))
            status_counts[pt.status] = status_counts.get(pt.status, 0) + 1
            if pt.status == "ok":
                total_inliers += pt.inliers
                total_matches += pt.ratio_filtered_matches
                if pt.inlier_ratio is not None:
                    ratios.append(pt.inlier_ratio)
                if pt.reprojection_error_px is not None:
                    reproj.append(pt.reprojection_error_px)
            if (i + 1) % 10 == 0 or i == len(neighbours) - 1:
                self.emit(
                    {
                        "type": "progress",
                        "stage": "match_features",
                        "done": i + 1,
                        "total": len(neighbours),
                        "label": "matching pairs",
                        "metrics": self._live_metrics(),
                    }
                )

        stats = {
            "pairs_attempted": len(pairs),
            "pairs_ok": status_counts.get("ok", 0),
            "pairs_failed": len(pairs) - status_counts.get("ok", 0),
            "status_counts": status_counts,
            "total_ratio_filtered_matches": total_matches,
            "total_inliers": total_inliers,
            "mean_inlier_ratio": statistics.fmean(ratios) if ratios else None,
            "mean_reprojection_error_px": statistics.fmean(reproj) if reproj else None,
            "images_decoded_failed": decodes_failed,
            "matching_megapixels": self.settings.matching_megapixels,
            "matching_scale": (
                round(feats[frames[0].frame_id].scale, 4) if frames and frames[0].frame_id in feats else None
            ),
            "matching_copy_size": (
                [feats[frames[0].frame_id].width, feats[frames[0].frame_id].height]
                if frames and frames[0].frame_id in feats
                else None
            ),
            "feature_detector": self.settings.feature_detector,
            "matching_seconds": time.perf_counter() - t_match,
        }
        # Persist the per-pair match/RANSAC evidence so the UI can show it.
        pairs_path = self.meta_dir / "pairs.json"
        pairs_path.write_text(
            json.dumps([p.to_dict() for p, _g in pairs], indent=1), encoding="utf-8"
        )
        self._add_artifact("pairs_json", pairs_path, "Pair match / RANSAC statistics")

        # Release descriptors: layout stays bounded on large datasets.
        for feat in feats.values():
            feat.descriptors = None
            feat.keypoints = []
        return pairs, stats

    # -- stage 5 ----------------------------------------------------------
    def _align_stage(self, frames, ingest_result, pairs) -> dict:
        s = self.settings
        canvas = define_canvas(
            frames,
            ingest_result.projector,
            s.max_output_megapixels,
            s.output_gsd_m,
        )

        # Heading convention + GPS-relative consistency gate, iterated once so the
        # gate uses the same convention the solve will use.
        gate_detail: dict = {}
        subset = pairs
        for _ in range(2):
            heading = resolve_heading_convention(frames, canvas, subset)
            seed = seed_poses(frames, canvas, heading["yaw_sign"], heading["heading_offset_deg"])
            subset, gate_detail = filter_pairs_by_seed_consistency(seed, subset)
            if not gate_detail.get("rejected"):
                break

        seed = seed_poses(frames, canvas, heading["yaw_sign"], heading["heading_offset_deg"])
        solved = solve_global_alignment(
            frames,
            canvas,
            subset,
            seed,
            gps_prior_weight=s.gps_prior_weight,
            max_nfev=max(60, s.global_max_iterations * 4),
        )

        anchor = anchor_to_gps(frames, canvas, solved.poses)
        gps_after = recompute_gps_stats(frames, canvas, solved.poses)

        # Homography comparison path
        homography_ok = 0
        comparison: dict = {"available": False}
        want_homography = s.alignment_model in ("homography", "both")
        if want_homography:
            homo_pairs = self._estimate_homography_pairs(frames, subset)
            homography_ok = sum(1 for p, _g in homo_pairs if p.status == "ok")
            chain = chain_homography_poses(frames, canvas, solved.poses, homo_pairs)
            comparison = compare_alignment_paths(frames, canvas, solved.poses, chain)
            comparison["homography_pairs_ok"] = homography_ok
            comparison["homography_pairs_attempted"] = len(homo_pairs)
            comparison["homography_status_counts"] = _count_statuses(homo_pairs)
            comparison["selected_composition_model"] = "affine (similarity on the UTM canvas)"
            comparison["selection_rationale"] = (
                "Composition always uses the global similarity solve because it is the model "
                "validated by the least-squares step. The homography chain is measured here for "
                "comparison only, so its numbers are evidence rather than the composite geometry."
            )

        return {
            "canvas": canvas,
            "poses": solved.poses,
            "pairs_used": subset,
            "heading": heading,
            "gate": gate_detail,
            "solver": solved.solver,
            "residuals": solved.residual_stats,
            "anchor": anchor,
            "gps_after": gps_after,
            "homography_ok": homography_ok,
            "comparison": comparison,
            "messages": solved.messages,
        }

    def _estimate_homography_pairs(self, frames, pairs):
        """Re-estimate the pair transforms with a homography model for comparison.

        Uses the correspondences already recorded, so this costs no extra
        feature work - only the robust fit.
        """
        by = by_id(frames)
        s = self.settings
        out = []
        for pair, geom in pairs:
            if geom is None:
                out.append((pair, None))
                continue
            src = _FakeFeatures(pair.source_id, geom.src_points)
            dst = _FakeFeatures(pair.target_id, geom.dst_points)
            mr = _fake_match(geom.src_points, geom.dst_points)
            pt, g = estimate_pair_transform(
                src, dst, mr, model="homography",
                ransac_threshold_px=s.ransac_threshold_px,
                ransac_confidence=s.ransac_confidence,
                ransac_max_iters=s.ransac_max_iters,
                min_inliers=s.min_inliers,
                max_reprojection_error_px=s.max_reprojection_error_px,
                gsd_m=(by.get(pair.source_id).gsd_m if by.get(pair.source_id) else None),
            )
            out.append((pt, g))
        return out

    # -- stage 6 ----------------------------------------------------------
    def _compose_stage(self, frames, poses, canvas, guard: MemoryGuard) -> dict:
        s = self.settings
        gains = (
            estimate_exposure_gains(frames, poses)
            if s.exposure_compensation
            else {}
        )
        preview = geopraster.PreviewAccumulator(canvas.width, canvas.height)
        writer = geopraster.GeoTiffWriter(
            self.out_dir / "orthomosaic.tif",
            canvas.width,
            canvas.height,
            canvas.gsd_m,
            canvas.origin_e,
            canvas.origin_n,
            canvas.crs_epsg if canvas.georeferenced else None,
            nodata=0,
        )
        with writer as w:
            def sink(tx: int, ty: int, rgba: np.ndarray) -> None:
                w.write_tile(tx, ty, rgba, s.tile_size)
                preview.add(tx, ty, rgba, s.tile_size)

            tiles, stats = compose_mosaic(
                frames,
                poses,
                canvas.width,
                canvas.height,
                tile_size=s.tile_size,
                decode_cache_size=s.decode_cache_size,
                max_decode_side=s.max_decode_side,
                seam_blend_px=s.seam_blend_px,
                gains=gains,
                sink=sink,
                on_tile=lambda tx, ty, done, total: self.emit(
                    {
                        "type": "progress",
                        "stage": "compose_tiles",
                        "done": done,
                        "total": total,
                        "label": f"writing tile {tx},{ty}",
                        "metrics": self._live_metrics(),
                    }
                ),
                on_first_tile=lambda sec: self.emit(
                    {"type": "first_tile", "seconds": sec, "metrics": self._live_metrics()}
                ),
                memory_check=guard.check,
            )
        self.frames_failed_during_run += int(stats.frames_failed or 0)
        raster_result = w.result()
        preview_meta = preview.save(self.out_dir / "preview.png")
        if preview_meta.get("produced"):
            self._add_artifact("preview_png", Path(preview_meta["path"]), "Mosaic preview (PNG)")

        stats_dict = stats.to_dict()
        stats_dict["tiles_covered"] = len(tiles) if tiles else stats.tiles_written
        stats_dict["preview"] = preview_meta
        stats_dict["exposure_gains"] = {
            "applied": bool(gains),
            "frames": len(gains),
            "range": [min(gains.values()), max(gains.values())] if gains else None,
        }
        stats_dict["raster"] = {
            "path": raster_result.path,
            "bytes": raster_result.bytes,
            "width": raster_result.width,
            "height": raster_result.height,
            "bands": raster_result.bands,
            "crs": raster_result.crs,
            "nodata": raster_result.nodata,
            "messages": raster_result.messages,
            "validation": raster_result.validation,
        }
        stats_dict["_raster"] = raster_result
        stats_dict["_preview"] = preview_meta
        return stats_dict

    # -- stages 7 and 8 ---------------------------------------------------
    def _georeference_and_export(self, canvas, poses, output: OutputMetadata, ingest_result) -> None:
        raster_result = getattr(self, "geotiff_result", None)
        preview_meta = getattr(self, "preview_meta", {})

        # ---- 7. Georeference ------------------------------------------
        self._start("georeference")
        with stage_timer() as t:
            if raster_result is None or not raster_result.path:
                self._skip("georeference", "no raster was produced by composition")
                output.produced = False
                output.kind = "none"
            else:
                output.produced = True
                output.crs = raster_result.crs
                output.crs_name = canvas.crs_name
                output.transform = raster_result.transform
                output.bounds = raster_result.bounds
                output.bounds_wgs84 = raster_result.bounds_wgs84
                output.width = raster_result.width
                output.height = raster_result.height
                output.bands = raster_result.bands
                output.gsd_m = canvas.gsd_m
                output.pixel_resolution_m = canvas.gsd_m
                output.nodata = raster_result.nodata
                output.geotiff_path = raster_result.path
                output.geotiff_bytes = raster_result.bytes
                output.alpha_mask = True
                output.preview_png = preview_meta.get("path")
                output.georeferencing_basis = canvas.basis
                output.validation = raster_result.validation
                output.messages = list(raster_result.messages)
                output.kind = (
                    "georeferenced_orthomosaic"
                    if raster_result.crs
                    else "preliminary_visual_mosaic"
                )
                if not raster_result.crs:
                    output.messages.append(
                        "No CRS was written: this is a preliminary visual mosaic, not a "
                        "georeferenced orthomosaic."
                    )
                cog = geopraster.convert_to_cog(
                    raster_result.path, self.out_dir / "orthomosaic_cog.tif"
                )
                output.cog_messages = cog.get("messages", [])
                if cog.get("produced"):
                    output.cog_path = cog["path"]
                    output.cog_bytes = cog["bytes"]
                    output.cog_driver = cog["driver"]
                    self._add_artifact("cog", Path(cog["path"]), "Cloud Optimized GeoTIFF")
                    # Verify the COG by reopening it, not by trusting the converter.
                    check = geopraster.validate_raster(cog["path"])
                    output.cog_validation = check.validation
                    if not check.width:
                        output.messages.append(
                            "COG was written but failed reopen validation; use the plain GeoTIFF."
                        )
                        output.cog_validation_failed = True
                output.messages.extend(output.cog_messages)
            self._add_artifact(
                "orthomosaic_preview",
                Path(preview_meta["path"]) if preview_meta.get("produced") else None,
                "Preview image",
            )
        self._finish(
            "georeference",
            t["elapsed_s"],
            {
                "kind": output.kind,
                "crs": output.crs,
                "bounds": output.bounds,
                "pixel_size_m": output.pixel_resolution_m,
                "cog": bool(output.cog_path),
                "validation_readable": bool(output.validation.get("readable")),
            },
            detail=(
                f"{output.kind}: {output.width}x{output.height} px at "
                f"{output.pixel_resolution_m * 100:.2f} cm/px"
                if output.width
                else "no raster"
            ),
        )

        # ---- 8. Export -------------------------------------------------
        self._start("export")
        with stage_timer() as t:
            tiles_info = {"produced": False, "messages": ["GeoTIFF unavailable"]}
            if raster_result and raster_result.path and raster_result.crs and raster_result.bounds_wgs84:
                min_z, max_z = geopraster.choose_zoom_range(
                    canvas.gsd_m, raster_result.bounds_wgs84
                )
                tiles_info = geopraster.generate_xyz_tiles(
                    raster_result.path, self.out_dir / "tiles", min_z, max_z
                )
                output.min_zoom = tiles_info.get("min_zoom")
                output.max_zoom = tiles_info.get("max_zoom")
                output.tiles_dir = tiles_info.get("dir")
                output.tile_count = tiles_info.get("tile_count")
                output.tiles_messages = tiles_info.get("messages", [])
                if tiles_info.get("produced"):
                    self._add_artifact(
                        "tiles",
                        Path(tiles_info["dir"]),
                        f"XYZ web tiles (z{min_z}-z{max_z})",
                        {"tile_count": tiles_info.get("tile_count")},
                    )
                output.messages.extend(tiles_info.get("messages", []))
            elif raster_result and raster_result.path and not raster_result.bounds_wgs84:
                tiles_info = {
                    "produced": False,
                    "messages": ["raster bounds could not be reprojected to WGS84"],
                }
                output.tiles_messages = tiles_info["messages"]
            output.tiles_produced = bool(tiles_info.get("produced"))
            output.tiles_messages = tiles_info.get("messages", [])

            frames_csv = self.meta_dir / "frames.csv"
            worst = geopraster.capabilities()
            self._finish(
                "export",
                t["elapsed_s"],
                {
                    "geotiff": bool(output.geotiff_path),
                    "geotiff_bytes": output.geotiff_bytes,
                    "cog": bool(output.cog_path),
                    "cog_bytes": output.cog_bytes,
                    "tiles": output.tiles_produced,
                    "tile_count": output.tile_count,
                    "tiles_zoom": [output.min_zoom, output.max_zoom],
                    "report_json": True,
                    "metrics_csv": True,
                    "frames_csv": frames_csv.exists(),
                    "tooling": {
                        "rio_cogeo_cli": worst["rio_cogeo_cli"],
                        "cog_driver": worst["cog_driver"],
                        "gdal2tiles": worst["gdal2tiles"],
                    },
                },
                detail=_export_summary(output),
            )

        self.output = output

    # -- reporting --------------------------------------------------------
    def _build_metrics(
        self, status, wall, ingest_result, plan, pairs, canvas, output, profile, enforcement,
        guard, query_total, matched_total,
    ) -> MetricsRecord:
        summary = self.sampler.summary(wall)
        cpu = summary["cpu"]
        disk = summary["disk"]
        m = MetricsRecord(run_id=self.run_id, profile=profile.name)
        m.wall_clock_s = wall
        m.peak_rss_mb = summary["peak_rss_mb"]
        m.baseline_rss_mb = summary["baseline_rss_mb"]
        m.peak_rss_delta_mb = summary["peak_rss_delta_mb"]
        m.cpu_cores_effective = cpu.get("cores_available_to_process")
        m.avg_cpu_percent = cpu.get("mean_percent_of_machine")
        m.peak_cpu_percent = cpu.get("peak_percent_of_machine")
        m.disk_read_bytes = disk.get("read_bytes")
        m.disk_write_bytes = disk.get("write_bytes")
        m.profile_limit_cores = profile.cpu_cores
        m.profile_limit_ram_mb = profile.ram_limit_mb
        m.profile_enforcement = dict(enforcement)
        m.stage_metrics = [s.to_dict() for s in self.stages]
        m.measurements_unavailable = []
        if m.disk_read_bytes is None:
            m.measurements_unavailable.append(f"disk I/O ({disk.get('reason')})")

        if ingest_result is not None:
            m.frames_total = len(ingest_result.frames)
            m.frames_accepted = len(ingest_result.accepted)
            m.frames_rejected = len(ingest_result.rejected)
            m.frames_failed = len(ingest_result.rejected) + self.frames_failed_during_run
            m.input_bytes = ingest_result.input_bytes

        m.feature_detector = self.settings.feature_detector
        m.alignment_model = self.settings.alignment_model
        m.matching_megapixels = self.settings.matching_megapixels
        m.tile_size = self.settings.tile_size
        m.output_crs = output.crs if output else None
        m.output_kind = output.kind if output else None

        feats = None
        for st in self.stages:
            if st.name == "match_features" and st.counters:
                feats = st.counters
        if feats:
            m.pairs_candidates = int(feats.get("pairs_attempted") or 0)
            m.pairs_matched = int(feats.get("pairs_ok") or 0)
            m.pairs_failed = int(feats.get("pairs_failed") or 0)
            m.total_matches = int(feats.get("total_ratio_filtered_matches") or 0)
            m.total_inliers = int(feats.get("total_inliers") or 0)
            m.mean_inlier_ratio = feats.get("mean_inlier_ratio")
            m.mean_reprojection_error_px = feats.get("mean_reprojection_error_px")

        for st in self.stages:
            if st.name == "compose_tiles":
                m.time_to_first_tile_s = st.counters.get("time_to_first_tile_s")
                m.frames_composed = st.counters.get("frames_composed")
            if st.name == "align":
                m.mean_gps_placement_error_m = st.counters.get("gps_placement_error_mean_m")

        if m.frames_accepted and m.wall_clock_s:
            m.throughput_fps = m.frames_accepted / m.wall_clock_s

        web_bytes: int | None = None
        if output is not None and output.produced:
            total_out = (output.geotiff_bytes or 0) + (output.cog_bytes or 0)
            tile_bytes = _dir_bytes(Path(output.tiles_dir)) if output.tiles_dir else 0
            total_out += tile_bytes
            m.output_bytes = total_out
            if m.input_bytes and total_out:
                m.reduction_factor = m.input_bytes / total_out
            # What a browser on the other end of a link actually has to fetch: the
            # COG plus the XYZ tiles. The lossless GeoTIFF is a local artifact and is
            # deliberately excluded from this figure.
            if output.cog_bytes:
                web_bytes = output.cog_bytes + tile_bytes
            elif output.tiles_dir and tile_bytes:
                web_bytes = tile_bytes
        m.bandwidth = bandwidth_table(m.input_bytes, m.output_bytes, web_bytes)

        if guard.limit_mb is not None:
            m.notes.append(
                f"{profile.name}: CPU affinity "
                f"{'applied' if enforcement.get('cpu_affinity_applied') else 'not applied'}; "
                f"RAM ceiling {guard.limit_mb} MB enforced as a soft abort limit"
                + (f" (peak seen {guard.peak_seen_mb:.0f} MB)" if guard.peak_seen_mb else "")
                + ". This is a configured constraint, not a physical device measurement."
            )
        else:
            m.notes.append(
                "laptop profile: no CPU or RAM constraint applied, so these numbers describe the "
                "host machine, not an edge device."
            )
        if m.peak_rss_mb is not None and m.baseline_rss_mb is not None:
            m.notes.append(
                f"Peak process RSS {m.peak_rss_mb:.0f} MB against a {m.baseline_rss_mb:.0f} MB baseline, "
                f"sampled every {summary['sampling_interval_s']:.2f}s ({summary['rss_samples']} samples)."
            )
        if m.time_to_first_tile_s is None:
            m.measurements_unavailable.append("time-to-first-tile (no tile was produced)")
        return m

    def _build_report(self, status, error, ingest_result, plan, canvas, output, metrics, enforcement, guard):
        align_stage = self._stage("align").counters
        report = {
            "run_id": self.run_id,
            "name": self.name,
            "status": status,
            "error": error,
            "created_at": self.started_at,
            "finished_at": utcnow(),
            "source": (
                ingest_result.discovery.to_dict() if ingest_result is not None else {"root": str(self.source)}
            ),
            "settings": self.settings.to_dict(),
            "profile": guard.profile_name,
            "profile_enforcement": enforcement,
            "crs": ingest_result.crs_name if ingest_result else None,
            "metadata_summary": ingest_result.summary if ingest_result else {},
            "dataset_warnings": ingest_result.dataset_warnings if ingest_result else [],
            "plan": plan.to_dict() if plan else None,
            "ingest_summary": ingest_result.summary if ingest_result else {},
            "stages": [s.to_dict() for s in self.stages],
            "metrics": metrics.to_dict(),
            "output": output.to_dict() if output else OutputMetadata().to_dict(),
            "messages": self.messages,
            "limitations": sorted(set(self.limitations + _STANDING_LIMITATIONS)),
        }
        if plan:
            report["plan"] = {
                "selection_method": plan.selection_method,
                "radius_m": plan.radius_m,
                "candidate_pairs": len(plan.neighbours),
                "all_pairs_possible": plan.all_pairs_possible,
                "pairs_below_overlap": plan.pairs_below_overlap,
                "reduction_factor": plan.reduction_factor,
                "notes": plan.notes,
                "pairs": [
                    {
                        "source_id": n.source_id,
                        "target_id": n.target_id,
                        "distance_m": n.distance_m,
                        "estimated_overlap": n.estimated_overlap,
                        "selection": n.selection,
                    }
                    for n in plan.neighbours
                ],
            }
        # pull align details recorded on the stage counters
        report["alignment"] = align_stage
        report["alignment_comparison"] = self._alignment_comparison
        report["canvas"] = canvas.to_dict() if canvas else None
        return report

    def _emit_final(self, status: str) -> None:
        self.emit(
            {
                "type": "finished",
                "run_id": self.run_id,
                "status": status,
                "report": self.report,
            }
        )


class PipelineStopped(Exception):
    """Raised to end a run early with an explanation already recorded."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


class _FakeFeatures:
    """Adapter so pairwise transforms can be refit from stored correspondences."""

    def __init__(self, frame_id: str, points: np.ndarray):
        self.frame_id = frame_id
        self.scale = 1.0
        self.keypoints = [type("K", (), {"pt": tuple(p)})() for p in points]
        self.count = len(self.keypoints)
        self.descriptors = None
        self.error = None


def _fake_match(src: np.ndarray, dst: np.ndarray):
    from .features.matching import MatchResult

    return MatchResult(
        status="ok",
        raw_matches=len(src),
        ratio_matches=len(src),
        src_points=src.reshape(-1, 1, 2).astype(np.float32),
        dst_points=dst.reshape(-1, 1, 2).astype(np.float32),
    )


def _count_statuses(pairs) -> dict:
    out: dict[str, int] = {}
    for pt, _g in pairs:
        out[pt.status] = out.get(pt.status, 0) + 1
    return out


def by_id(frames) -> dict:
    return {f.frame_id: f for f in frames}


def _dir_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def _export_summary(output: OutputMetadata) -> str:
    bits = []
    if output.geotiff_path:
        bits.append(f"GeoTIFF {human_bytes(output.geotiff_bytes)}")
    if output.cog_path:
        bits.append(f"COG {human_bytes(output.cog_bytes)}")
    if output.tiles_produced:
        bits.append(f"{output.tile_count} XYZ tiles")
    bits.append("report.json")
    bits.append("metrics.csv")
    return ", ".join(bits)


_STANDING_LIMITATIONS = [
    "Targets mostly flat, nadir RGB drone surveys. Strong terrain relief or large parallax "
    "breaks the 2D flat-ground assumption; this is not terrain-aware orthorectification.",
    "Not survey grade. No ground control points were used, so no accuracy claim beyond "
    "self-consistency against the camera's own GPS tags is made.",
    "No 3D products: no point cloud, DSM or mesh. EdgeOrtho deliberately stops at a 2D map.",
    "GPS placement error is measured against the camera's own EXIF/XMP tags, which are not "
    "an independent reference.",
    "Constrained profiles emulate CPU and RAM limits on this host. They do not predict the "
    "runtime or memory of a physical Raspberry Pi or Jetson device.",
]


def _write_frames_csv(path: Path, ingest_result) -> None:
    fields = [
        "frame_id", "filename", "bytes", "accepted", "reject_reason", "latitude", "longitude",
        "altitude_m", "altitude_source", "yaw_deg", "yaw_source", "width", "height", "make",
        "model", "focal_length_mm", "focal_length_35mm", "gsd_m", "gsd_source",
        "footprint_w_m", "footprint_h_m", "projected_x", "projected_y", "captured_at",
        "warnings",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for f in ingest_result.frames:
            row = f.to_dict()
            row["warnings"] = ";".join(f.warnings)
            writer.writerow(row)


def _write_metrics_csv(path: Path, metrics: MetricsRecord) -> None:
    flat = {k: v for k, v in asdict(metrics).items() if not isinstance(v, (dict, list))}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(flat.keys()))
        writer.writeheader()
        writer.writerow(flat)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def run_pipeline(
    source: str | list[str],
    settings: config.PipelineSettings | None = None,
    run_id: str | None = None,
    name: str | None = None,
    emit: Emitter | None = None,
) -> dict:
    """Run the pipeline once and return the full report."""
    config.ensure_dirs()
    rid = run_id or (
        datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    )
    label = name or (Path(source).name if isinstance(source, str) else "uploaded set")
    return PipelineRun(rid, label, source, settings, emit).run()
