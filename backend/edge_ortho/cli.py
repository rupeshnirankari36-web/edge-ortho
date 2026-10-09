"""EdgeOrtho command line interface.

The brief's evidence package asks for "one command that processes a geotagged
folder", so that is exactly what ``edgeortho run`` is. ``serve`` starts the local
API and the built desktop UI on the same machine.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config
from .geo import raster as geopraster
from .ingest.validate import ingest
from .pipeline import run_pipeline
from .profiles import PROFILES
from .sample import fetch_sample, images_dir, is_installed, list_samples


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--profile", default="laptop", choices=sorted(PROFILES), help="resource profile")
    p.add_argument(
        "--preset",
        default="balanced",
        choices=sorted(config.PRESETS),
        help="settings preset",
    )
    p.add_argument("--alignment", dest="alignment_model", choices=["affine", "homography", "both"])
    p.add_argument("--matching-mp", dest="matching_megapixels", type=float, help="matching copy megapixels")
    p.add_argument("--tile-size", dest="tile_size", type=int, help="output tile size in pixels")
    p.add_argument("--max-output-mp", dest="max_output_megapixels", type=float, help="output pixel cap")
    p.add_argument("--gps-prior", dest="gps_prior_weight", type=float, help="weak GPS prior weight")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edgeortho",
        description=(
            "EdgeOrtho - local, edge-optimised 2D drone orthomosaic generation. "
            "Raw imagery never leaves the machine."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="process a folder of geotagged drone images")
    run.add_argument("input", help="folder (or single image) containing drone imagery")
    run.add_argument("--out", help="output folder (defaults to outputs/<run id>)")
    run.add_argument("--name", help="human readable run name")
    run.add_argument("--json", action="store_true", help="print the full report as JSON")
    _add_common(run)

    inspect = sub.add_parser("inspect", help="validate metadata only; no processing")
    inspect.add_argument("input")
    inspect.add_argument("--json", action="store_true")

    serve = sub.add_parser("serve", help="start the local API and desktop UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    samples = sub.add_parser("samples", help="list or fetch small public sample datasets")
    samples.add_argument("action", choices=["list", "fetch"], nargs="?", default="list")
    samples.add_argument("key", nargs="?", help="sample key, e.g. brighton_beach")

    sub.add_parser("profiles", help="show the resource profiles and detected capabilities")
    return parser


def cmd_run(args: argparse.Namespace) -> int:
    overrides = {
        k: v
        for k, v in {
            "alignment_model": args.alignment_model,
            "matching_megapixels": args.matching_megapixels,
            "tile_size": args.tile_size,
            "max_output_megapixels": args.max_output_megapixels,
            "gps_prior_weight": args.gps_prior_weight,
        }.items()
        if v is not None
    }
    settings = config.resolve_settings(profile=args.profile, preset=args.preset, overrides=overrides)

    def emit(event: dict) -> None:
        kind = event.get("type")
        if kind == "stage":
            s = event["stage"]
            note = s.get("detail") or s.get("unsupported_reason") or s.get("error") or ""
            elapsed = f"{s['elapsed_s']:.2f}s" if s.get("elapsed_s") is not None else ""
            print(f"  {s['name']:<18} {s['status']:<8} {elapsed:>8}  {note}")
        elif kind == "first_tile":
            print(f"  time-to-first-tile: {event['seconds']:.2f}s")

    print(f"EdgeOrtho run | profile={settings.profile} preset={settings.preset}")
    print(f"source: {args.input}")
    report = run_pipeline(args.input, settings=settings, name=args.name, emit=emit)

    if args.out:
        target = Path(args.out)
        target.mkdir(parents=True, exist_ok=True)
        src = config.OUTPUT_DIR / report["run_id"]
        import shutil

        if src.exists():
            for item in src.iterdir():
                dest = target / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        m = report["metrics"]
        o = report["output"]
        print()
        print(f"status          : {report['status']}" + (f"  ({report['error']})" if report["error"] else ""))
        print(f"output          : {o.get('kind')} - {o.get('width')}x{o.get('height')} px @ "
              f"{(o.get('pixel_resolution_m') or 0) * 100:.2f} cm/px")
        print(f"crs             : {o.get('crs')}  ({o.get('crs_name')})")
        print(f"bounds wgs84    : {o.get('bounds_wgs84')}")
        print(f"geotiff / cog   : {o.get('geotiff_bytes')} / {o.get('cog_bytes')} bytes")
        print(f"xyz tiles       : {o.get('tile_count')} (z{o.get('min_zoom')}-z{o.get('max_zoom')})")
        print(f"wall clock      : {m.get('wall_clock_s'):.1f} s")
        print(f"time first tile : {m.get('time_to_first_tile_s')}")
        print(f"peak RSS        : {m.get('peak_rss_mb')} MB (baseline {m.get('baseline_rss_mb')} MB)")
        print(f"frames          : {m.get('frames_accepted')} accepted / {m.get('frames_rejected')} rejected")
        print(f"pairs           : {m.get('pairs_matched')}/{m.get('pairs_candidates')} matched, "
              f"{m.get('total_inliers')} inliers")
        print(f"gps consistency : {m.get('mean_gps_placement_error_m')} m (vs camera GPS tags)")
        bw = m.get("bandwidth") or {}
        for mbps, row in (bw.get("scenarios") or {}).items():
            print(f"  @{mbps:>2} Mbps     : raw {row['input_human']}  ->  products {row['output_human']}"
                  + (f"  (saved {row['saved_human']})" if row.get("saved_human") else ""))
        if m.get("measurements_unavailable"):
            print(f"unavailable     : {', '.join(m['measurements_unavailable'])}")
        print(f"outputs         : {config.OUTPUT_DIR / report['run_id']}")
    return 0 if report["status"] == "succeeded" else 1


def cmd_inspect(args: argparse.Namespace) -> int:
    result = ingest(args.input)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0
    s = result.summary
    print(f"source        : {getattr(result.discovery.root, '__str__', lambda: None)()}")
    print(f"discovered    : {s['frames_discovered']} image file(s)")
    print(f"accepted      : {s['frames_accepted']}")
    print(f"rejected      : {s['frames_rejected']} {s['rejected_by_reason'] or ''}")
    print(f"GPS           : {'yes' if s['gps_available'] else 'NO - unusable for mapping'}")
    print(f"altitude      : {s['altitude_range_m']} m ({s['altitude_source']})")
    print(f"yaw           : {s['yaw_available']} ({s['yaw_source']})")
    print(f"estimated GSD : {s['gsd_m']} m/px ({s['gsd_source']})")
    print(f"footprint     : {s['footprint_m']} m across")
    print(f"image sizes   : {', '.join(s['image_dimensions'])}")
    print(f"cameras       : {', '.join(s['camera_models'])}")
    print(f"crs           : {result.crs_name}")
    print(f"suitable      : {result.suitable}")
    if s["flight_extent"]:
        e = s["flight_extent"]
        print(f"flight extent : {e['width_m']:.0f} x {e['height_m']:.0f} m")
    for w in result.dataset_warnings:
        print(f"warning       : {w['code']} - {w['detail']}")
    if result.unsuitability_reasons:
        print(f"reasons       : {'; '.join(result.unsuitability_reasons)}")
    return 0 if result.suitable else 2


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    config.ensure_dirs()
    print(f"EdgeOrtho API on http://{args.host}:{args.port}")
    dist = config.PROJECT_ROOT / "frontend" / "dist"
    if dist.exists():
        print(f"serving the built UI from {dist}")
    else:
        print("no built UI found; run `npm run build` in frontend/ or use `npm run dev`")
    uvicorn.run(
        "edge_ortho.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


def cmd_samples(args: argparse.Namespace) -> int:
    if args.action == "list":
        for meta in list_samples():
            installed = is_installed(meta["key"])
            print(f"{meta['key']:<16} {meta['label']:<26} ~{meta['approx_bytes'] / 1e6:.0f} MB  "
                  f"{'installed' if installed else 'not installed'}")
            print(f"                 {meta['description']}")
            print(f"                 licence: {meta['license']}")
            print(f"                 source : {meta['repo']}")
        return 0
    if not args.key:
        print("usage: edgeortho samples fetch <key>", file=sys.stderr)
        return 2
    manifest = fetch_sample(args.key, progress=lambda m: print(f"  {m}"))
    print(json.dumps(manifest, indent=2))
    folder = images_dir(args.key)
    print(f"\nrun it with:\n  edgeortho run \"{folder}\" --preset balanced --profile laptop")
    return 0


def cmd_profiles(_args: argparse.Namespace) -> int:
    caps = geopraster.capabilities()
    print("Resource profiles (configured limits, not physical device measurements):\n")
    for p in PROFILES.values():
        cores = "all host cores" if p.cpu_cores is None else f"{p.cpu_cores} cores"
        ram = "no ceiling" if p.ram_limit_mb is None else f"{p.ram_limit_mb} MB soft ceiling"
        star = " *acceptance profile*" if p.acceptance else ""
        print(f"  {p.name:<14} {cores:<16} {ram}{star}")
        print(f"                 {p.description}")
    print("\nGeospatial tooling detected on this machine:\n")
    for key in ("rasterio", "cog_driver", "rio_cogeo_cli", "gdalinfo", "gdal_translate", "gdal2tiles"):
        print(f"  {key:<16} {caps.get(key)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config.ensure_dirs()
    handlers = {
        "run": cmd_run,
        "inspect": cmd_inspect,
        "serve": cmd_serve,
        "samples": cmd_samples,
        "profiles": cmd_profiles,
    }
    return handlers[args.command](args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
