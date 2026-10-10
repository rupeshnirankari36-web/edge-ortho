"""End-to-end check of the local EdgeOrtho API.

The point of this script is to exercise the product the way a user does - through
the HTTP API - and then verify the artifacts that were actually written to disk:

1. ``POST /api/sources/inspect``   - metadata validation for a folder of frames
2. ``POST /api/runs``              - start a run and follow its SSE stream
3. ``GET  /api/runs/<id>/report``  - read the stored report back
4. reopen the GeoTIFF, the preview and the tiles with rasterio / Pillow

It fails loudly: any stage that did not produce what it claims produces a non-zero
exit status. Usage::

    python scripts/e2e_check.py --source data/raw/brighton_beach/images
    python scripts/e2e_check.py --source <folder> --profile pi-class --alignment both

No third-party HTTP client is required; only rasterio/Pillow for the artifact checks.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def request(base: str, path: str, method: str = "GET", payload: dict | None = None) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as response:  # noqa: S310 - localhost only
            body = response.read()
    except urllib.error.HTTPError as exc:  # pragma: no cover - exercised only on failure
        raise SystemExit(f"HTTP {exc.code} for {method} {path}: {exc.read().decode('utf-8')[:400]}")
    return json.loads(body) if body else None


def stream_run(base: str, run_id: str, timeout_s: float) -> list[dict]:
    """Follow the run's SSE stream and return the events, for progress reporting."""
    events: list[dict] = []
    deadline = time.time() + timeout_s
    req = urllib.request.Request(f"{base}/api/runs/{run_id}/events")
    with urllib.request.urlopen(req, timeout=timeout_s + 30) as response:  # noqa: S310
        for raw in response:
            if time.time() > deadline:
                print("  ! stream timed out; continuing with polling")
                break
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            events.append(event)
            kind = event.get("type")
            if kind == "stage":
                stage = event.get("stage", {})
                print(f"  · {stage.get('name'):<16} {stage.get('status'):<8} {stage.get('detail') or ''}")
            elif kind == "first_tile":
                print(f"  · first output tile written after {event.get('seconds'):.2f}s")
            elif kind == "finished":
                print(f"  · run {event.get('status')}")
                break
    return events


def check_geotiff(path: Path) -> dict:
    import rasterio

    with rasterio.open(path) as src:
        result = {
            "readable": True,
            "driver": src.driver,
            "width": src.width,
            "height": src.height,
            "count": src.count,
            "dtype": src.dtypes[0],
            "crs": str(src.crs) if src.crs else None,
            "crs_epsg": src.crs.to_epsg() if src.crs else None,
            "transform": [round(v, 6) for v in src.transform[:6]],
            "bounds": [round(v, 3) for v in src.bounds],
            "pixel_size_m": round(abs(src.transform.a), 6),
            "nodata": src.nodata,
            "cog_layout": bool(src.is_tiled),
            "overviews": list(src.overviews(1)),
            "block_shape": list(src.block_shapes[0]),
        }
        # Read real pixels from the interior: a raster whose first block is masked out
        # (a staircase mosaic corner) is not empty, so sampling 0,0 would be a lie in
        # the other direction. Coverage is reported so the number can be judged.
        size = min(512, src.width // 2 or src.width, src.height // 2 or src.height)
        offset_x = max(0, (src.width - size) // 2)
        offset_y = max(0, (src.height - size) // 2)
        window = rasterio.windows.Window(offset_x, offset_y, size, size)
        sample = src.read(window=window)
        rgb = sample[:3]
        result["sample_mean"] = round(float(rgb.mean()), 2)
        result["sample_nonzero_fraction"] = round(float((rgb.sum(axis=0) > 0).mean()), 4)
        if sample.shape[0] >= 4:
            alpha = sample[3]
            result["sample_alpha_coverage"] = round(float((alpha > 0).mean()), 4)
        coverage = _coverage_fraction(src)
        result["data_coverage"] = round(coverage, 4)
    return result


def _coverage_fraction(src) -> float:
    """Share of the raster that holds data, measured on a coarse grid (not assumed)."""
    import numpy as np

    data = src.read(1, out_shape=(min(512, src.height), min(512, src.width)))
    return float(np.count_nonzero(data) / data.size)


def check_png(path: Path) -> dict:
    from PIL import Image

    with Image.open(path) as im:
        return {"readable": True, "format": im.format, "size": list(im.size), "mode": im.mode}


def main() -> int:
    parser = argparse.ArgumentParser(description="EdgeOrtho end-to-end API check")
    parser.add_argument("--base", default="http://127.0.0.1:8077", help="API base URL")
    parser.add_argument("--source", required=True, help="folder of geotagged images")
    parser.add_argument("--name", default=None, help="run name")
    parser.add_argument("--profile", default="laptop")
    parser.add_argument("--preset", default="balanced")
    parser.add_argument("--alignment", default="affine", choices=["affine", "homography", "both"])
    parser.add_argument("--matching-mp", type=float, default=None)
    parser.add_argument("--tile-size", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--require-raster", action="store_true", default=True)
    parser.add_argument("--json-out", default=None, help="write the verification summary here")
    args = parser.parse_args()

    print(f"1. inspecting {args.source}")
    inspection = request(args.base, "/api/sources/inspect", "POST", {"path": args.source})
    summary = inspection["summary"]
    print(
        f"   {summary['frames_accepted']} accepted / {summary['frames_rejected']} rejected "
        f"of {inspection['discovery']['image_count']} discovered "
        f"({summary['total_bytes'] / 1e6:.1f} MB)"
    )
    print(f"   GPS={summary['gps_available']} altitude={summary['altitude_available']} yaw={summary['yaw_available']} gsd={summary['gsd_m']}")
    for warning in inspection["dataset_warnings"]:
        print(f"   ! {warning['text']}: {warning['detail']}")
    if not inspection["suitable"]:
        print(f"   x dataset is not suitable: {inspection['unsuitability_reasons']}")
        return 2

    settings = {"profile": args.profile, "preset": args.preset, "alignment_model": args.alignment}
    if args.matching_mp is not None:
        settings["matching_megapixels"] = args.matching_mp
    if args.tile_size is not None:
        settings["tile_size"] = args.tile_size

    name = args.name or f"e2e {Path(args.source).name} {args.profile}"
    print(f"2. starting run {name!r} with {settings}")
    created = request(args.base, "/api/runs", "POST", {"source": args.source, "name": name, "settings": settings})
    run_id = created["run_id"]
    print(f"   run_id={run_id}")
    stream_run(args.base, run_id, args.timeout)

    report = request(args.base, f"/api/runs/{run_id}/report.json")
    metrics = report.get("metrics") or {}
    output = report.get("output") or {}
    print(f"3. report: status={report['status']} wall={metrics.get('wall_clock_s')}s peak_rss={metrics.get('peak_rss_mb')}MB")
    print(
        f"   frames accepted={metrics.get('frames_accepted')} rejected={metrics.get('frames_rejected')} "
        f"failed={metrics.get('frames_failed')} composed={metrics.get('frames_composed')}"
    )
    print(
        f"   pairs candidate={metrics.get('pairs_candidates')} matched={metrics.get('pairs_matched')} "
        f"failed={metrics.get('pairs_failed')} inliers={metrics.get('total_inliers')}"
    )
    print(f"   output kind={output.get('kind')} produced={output.get('produced')} bytes={metrics.get('output_bytes')}")

    verification: dict[str, Any] = {"run_id": run_id, "status": report["status"], "checks": {}}
    failures: list[str] = []

    geotiff = output.get("geotiff_path")
    if geotiff and Path(geotiff).exists():
        info = check_geotiff(Path(geotiff))
        verification["checks"]["geotiff"] = info
        print(f"4. GeoTIFF {info['width']}x{info['height']} {info['crs']} px={info['pixel_size_m']}m bands={info['count']}")
        if not info["crs_epsg"]:
            failures.append("GeoTIFF has no CRS")
        if not info["readable"] or info["data_coverage"] == 0:
            failures.append("GeoTIFF read back with no data pixels")
        if info["data_coverage"] < 0.05:
            failures.append(f"GeoTIFF coverage is implausibly low ({info['data_coverage']})")
    elif args.require_raster:
        failures.append("no GeoTIFF was produced")

    cog = output.get("cog_path")
    if cog and Path(cog).exists():
        verification["checks"]["cog"] = check_geotiff(Path(cog))
        print(f"   COG {output.get('cog_driver')} {output.get('cog_bytes')} bytes; tiled={verification['checks']['cog']['cog_layout']}")

    preview = output.get("preview_png")
    if preview and Path(preview).exists():
        verification["checks"]["preview"] = check_png(Path(preview))
        print(f"   preview {verification['checks']['preview']['size']}")

    tile_count = output.get("tile_count") or 0
    if output.get("tiles_dir"):
        tiles = list(Path(output["tiles_dir"]).rglob("*.png"))
        verification["checks"]["tiles"] = {"count": len(tiles), "reported": tile_count}
        print(f"   XYZ tiles on disk: {len(tiles)} (reported {tile_count}), zoom z{output.get('min_zoom')}-z{output.get('max_zoom')}")
        if len(tiles) != tile_count:
            failures.append(f"tile count mismatch: {len(tiles)} on disk vs {tile_count} reported")
        if tiles:
            verification["checks"]["tile_sample"] = check_png(tiles[0])

    for kind in ("metadata_json", "frames_csv", "report_json", "metrics_csv"):
        artifact = next((a for a in report.get("artifacts") or [] if a["kind"] == kind), None)
        if artifact:
            exists = Path(artifact["path"]).exists()
            verification["checks"][kind] = {"path": artifact["path"], "exists": exists}
            if not exists:
                failures.append(f"artifact {kind} missing at {artifact['path']}")

    if metrics.get("peak_rss_mb") is None:
        failures.append("peak RSS was not measured")
    if metrics.get("wall_clock_s") is None:
        failures.append("wall clock was not measured")
    if metrics.get("time_to_first_tile_s") is None and output.get("produced"):
        failures.append("time to first tile was not measured")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(verification, indent=2), encoding="utf-8")
        print(f"5. wrote {args.json_out}")

    if failures:
        print("FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: the API produced and validated a georeferenced raster with measured metrics")
    return 0


if __name__ == "__main__":
    sys.exit(main())
