"""End-to-end pipeline runner integrating all stages."""

import datetime
import json
import logging
import platform
import time
from pathlib import Path

import numpy as np

from .align import (
    TransformModel,
    estimate_pair_transform,
    solve_global_poses,
)
from .compose import (
    compose_tiles_streaming,
    compute_canvas_layout,
)
from .config import PipelineConfig
from .features import (
    extract_features_from_image,
    get_feature_detector,
    match_feature_pair,
)
from .geo import (
    calculate_georeference_transform,
    convert_to_cog,
    create_empty_geotiff,
    generate_xyz_tiles,
    write_tile_to_geotiff,
)
from .ingest import ingest_and_validate_directory
from .monitor import (
    ResourceMonitor,
    RunSummary,
    save_samples_to_csv,
)
from .plan import (
    build_neighbor_graph,
    populate_gsd_and_headings,
    project_records_to_utm,
)
from .report import (
    build_markdown_report,
    generate_resource_chart,
)

logger = logging.getLogger("edge_ortho")


def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    config: PipelineConfig,
) -> RunSummary:
    """Executes the full edge orthomosaic pipeline under bounded resource limits."""
    output_dir.mkdir(parents=True, exist_ok=True)
    t_start = time.perf_counter()

    # 0. Initialize telemetry monitor
    monitor = ResourceMonitor(sample_interval_sec=0.5)
    monitor.start()

    summary = RunSummary(
        run_id=config.run_id,
        profile=config.profile_name,
        preset=config.preset_name,
        dataset_name=input_dir.name,
        metadata={
            "timestamp": datetime.datetime.now().isoformat(),
            "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "python": platform.python_version(),
        },
    )

    try:
        # STAGE 1: INGEST
        monitor.set_stage("ingest")
        ingest_res = ingest_and_validate_directory(input_dir)
        summary.total_frames_found = ingest_res.total_found
        summary.frames_accepted = ingest_res.accepted_count
        summary.frames_rejected = ingest_res.rejected_count

        if summary.frames_accepted == 0:
            raise ValueError(f"No valid geotagged frames accepted from {input_dir}")

        # Compute total input size
        summary.input_bytes = sum(r.path.stat().st_size for r in ingest_res.records)

        # STAGE 2: PLAN
        monitor.set_stage("plan")
        records = ingest_res.records
        epsg_code = project_records_to_utm(records)
        populate_gsd_and_headings(records)

        # Build neighbor graph
        neighbor_pairs = build_neighbor_graph(
            records,
            k_neighbors=config.k_neighbors,
            max_distance_meters=config.max_neighbor_distance_m,
        )

        # STAGE 3: MATCH
        monitor.set_stage("match")
        detector = get_feature_detector(
            matcher_name=config.matcher,
            feature_limit=config.feature_limit,
        )

        # Extract features for all accepted frames
        frame_features = {}
        for r in records:
            feat = extract_features_from_image(
                image_path=r.path,
                frame_id=r.frame_id,
                detector=detector,
                max_dim=config.matching_image_max_dim,
            )
            if feat:
                frame_features[r.frame_id] = feat

        # Match adjacent pairs
        pair_transforms = []
        inlier_ratios = []
        reproj_errors = []

        tf_model = TransformModel(config.transform_model.lower())

        for npair in neighbor_pairs:
            f1 = frame_features.get(npair.source_id)
            f2 = frame_features.get(npair.target_id)
            if not f1 or not f2:
                continue

            matched = match_feature_pair(
                f1,
                f2,
                ratio_threshold=config.ratio_test_threshold,
            )
            if not matched:
                continue

            summary.total_matches_evaluated += 1

            pt = estimate_pair_transform(
                source_id=matched.source_id,
                target_id=matched.target_id,
                src_points=matched.src_points,
                tgt_points=matched.tgt_points,
                model=tf_model,
                ransac_thresh_px=config.ransac_thresh_px,
                min_inliers=config.min_inliers,
            )
            pair_transforms.append(pt)

            if pt.status == "success":
                summary.total_inliers_found += pt.num_inliers
                inlier_ratios.append(pt.inlier_ratio)
                reproj_errors.append(pt.reprojection_error)

        if inlier_ratios:
            summary.mean_inlier_ratio = float(np.mean(inlier_ratios))
        if reproj_errors:
            summary.mean_reprojection_error = float(np.mean(reproj_errors))

        # Clear feature memory
        del frame_features

        # STAGE 4: ALIGN (Global Solve)
        monitor.set_stage("align")
        target_gsd = (
            float(np.median([r.gsd_m for r in records if r.gsd_m]))
            * config.output_resolution_factor
        )
        poses = solve_global_poses(
            records=records,
            pair_transforms=pair_transforms,
            target_gsd=target_gsd,
            gps_prior_weight=config.gps_prior_weight,
        )

        # STAGE 5: COMPOSE & GEO
        monitor.set_stage("compose")
        layout = compute_canvas_layout(records, poses)

        transform_affine, bounds_utm, bounds_wgs84 = calculate_georeference_transform(
            records=records,
            layout=layout,
            gsd_m=target_gsd,
            epsg_code=epsg_code,
        )

        geotiff_path = output_dir / "orthomosaic.tif"
        writer = create_empty_geotiff(
            output_path=geotiff_path,
            width=layout.width_px,
            height=layout.height_px,
            transform=transform_affine,
            epsg_code=epsg_code,
            bands=4,
        )

        def _on_first_tile(tile_res):
            monitor.record_first_tile()

        tile_generator = compose_tiles_streaming(
            records=records,
            layout=layout,
            tile_size=config.tile_size,
            feather_radius=config.feather_radius_px,
            exposure_compensation=config.exposure_compensation,
            on_first_tile_callback=_on_first_tile,
        )

        for tile in tile_generator:
            write_tile_to_geotiff(writer, tile)

        writer.close()
        summary.output_geotiff_bytes = geotiff_path.stat().st_size

        # STAGE 6: EXPORT (COG and XYZ Tiles)
        monitor.set_stage("export")
        cog_path = None
        if config.generate_cog:
            cog_target = output_dir / "orthomosaic_cog.tif"
            cog_res = convert_to_cog(geotiff_path, cog_target)
            if cog_res and cog_res.exists():
                cog_path = cog_res
                summary.output_cog_bytes = cog_res.stat().st_size

        tiles_dir = None
        if config.generate_tiles:
            tiles_dir = output_dir / "tiles"
            generate_xyz_tiles(
                geotiff_path=geotiff_path,
                output_tiles_dir=tiles_dir,
                bounds_wgs84=bounds_wgs84,
                min_zoom=config.tile_min_zoom,
                max_zoom=config.tile_max_zoom,
            )

        # STAGE 7: REPORT & TELEMETRY
        monitor.set_stage("report")
        monitor.stop()

        t_total = time.perf_counter() - t_start
        summary.total_latency_seconds = t_total
        summary.time_to_first_tile_seconds = monitor.time_to_first_tile
        summary.peak_rss_ram_mb = monitor.get_peak_ram_mb()
        summary.avg_cpu_percent = monitor.get_avg_cpu_percent()
        summary.stages = monitor.get_stage_durations()

        out_bytes = summary.output_cog_bytes or summary.output_geotiff_bytes
        if out_bytes > 0:
            summary.bandwidth_reduction_factor = float(summary.input_bytes) / float(out_bytes)

        # Save metrics CSV & JSON
        save_samples_to_csv(monitor.samples, output_dir / "metrics.csv")
        summary.save_json(output_dir / "metrics.json")
        summary.save_json(output_dir / "report.json")

        # Save resource plot
        generate_resource_chart(
            monitor.samples,
            output_dir / "resources.png",
            title=f"Edge Ortho: {config.profile_name} on {input_dir.name}",
        )

        # Save Markdown Report
        build_markdown_report(summary, output_dir / "report.md")

        # Save Viewer Manifest
        manifest = {
            "name": f"Orthomosaic - {input_dir.name}",
            "bounds_wgs84": list(bounds_wgs84),
            "bounds_utm": list(bounds_utm),
            "epsg": epsg_code,
            "width": layout.width_px,
            "height": layout.height_px,
            "gsd_m": target_gsd,
            "geotiff": str(geotiff_path.relative_to(output_dir)),
            "cog": str(cog_path.relative_to(output_dir)) if cog_path else None,
            "tiles": "tiles/{z}/{x}/{y}.png" if tiles_dir else None,
            "tile_metadata": "tiles/metadata.json" if tiles_dir else None,
            "metrics": "metrics.json",
        }
        with open(output_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        return summary

    except Exception as e:
        monitor.stop()
        logger.exception("Pipeline execution failed")
        raise e
