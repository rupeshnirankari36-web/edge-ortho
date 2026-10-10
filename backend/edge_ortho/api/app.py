"""FastAPI backend for the EdgeOrtho desktop application.

Everything is local: the API runs on the same machine as the imagery, the raw
frames are read from disk in place, and no request leaves the host. The API is
therefore the natural companion to the "privacy by default" claim rather than an
afterthought.

Two ingestion routes are supported on purpose:

* ``/api/sources/inspect`` with a local folder path - the true local-first path,
  which transfers zero bytes (the browser and the pipeline share a filesystem);
* ``/api/sources/upload`` with multipart files - for when the images live on
  another machine or the user prefers the browser drag-and-drop flow.
"""

from __future__ import annotations

import io
import json
import os
import platform
import queue
import shutil
import sys
import time
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from .. import config
from ..contracts import BANDWIDTH_TEST_MBPS
from ..geo import raster as geopraster
from ..ingest.validate import ingest
from ..profiles import PROFILES
from ..sample import fetch_sample, images_dir, is_installed, list_samples
from ..storage import RunStore
from .jobs import JobManager

VERSION = "0.1.0"

app = FastAPI(title="EdgeOrtho", version=VERSION, docs_url="/api/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = RunStore()
jobs = JobManager(store)


# ---------------------------------------------------------------------------
# system
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": VERSION, "time": time.time()}


@app.get("/api/system")
def system() -> dict:
    caps = geopraster.capabilities()
    import psutil

    vm = psutil.virtual_memory()
    return {
        "version": VERSION,
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()}",
        "cpu_logical": psutil.cpu_count(logical=True),
        "cpu_physical": psutil.cpu_count(logical=False),
        "ram_total_mb": round(vm.total / (1024 * 1024)),
        "data_dir": str(config.DATA_DIR),
        "output_dir": str(config.OUTPUT_DIR),
        "profiles": [p.to_dict() for p in PROFILES.values()],
        "presets": [
            {"name": p.name, "label": p.label, "description": p.description, "settings": p.settings}
            for p in config.PRESETS.values()
        ],
        "default_settings": config.PipelineSettings().to_dict(),
        "capabilities": {
            "rasterio": caps["rasterio"],
            "cog_driver": caps["cog_driver"],
            "rio_cogeo_cli": caps["rio_cogeo_cli"],
            "gdal2tiles": caps["gdal2tiles"],
            "xyz_tiles": caps["rasterio"],
            "opencv": _module_version("cv2"),
            "numpy": _module_version("numpy"),
            "pyproj": _module_version("pyproj"),
        },
        "active_run_id": jobs.active_run_id(),
        "supported_extensions": sorted(config.SUPPORTED_EXTENSIONS),
    }


def _module_version(name: str) -> str | None:
    try:
        mod = __import__(name)
        return getattr(mod, "__version__", "present")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------


@app.get("/api/browse")
def browse(path: str | None = Query(default=None)) -> dict:
    """List directories and image counts so the UI can offer a folder picker."""
    target = Path(path) if path else Path.home()
    try:
        target = target.expanduser().resolve()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"cannot resolve path: {exc}") from exc
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail=f"not a directory: {target}")

    dirs, image_count, other_count = [], 0, 0
    try:
        for entry in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    dirs.append({"name": entry.name, "path": str(entry)})
                elif entry.is_file():
                    if entry.suffix.lower() in config.SUPPORTED_EXTENSIONS:
                        image_count += 1
                    else:
                        other_count += 1
            except OSError:
                continue
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f"permission denied: {exc}") from exc

    return {
        "path": str(target),
        "parent": str(target.parent) if target.parent != target else None,
        "directories": dirs[:400],
        "images_here": image_count,
        "other_files_here": other_count,
        "quota": {
            "free_bytes": shutil.disk_usage(target).free,
            "total_bytes": shutil.disk_usage(target).total,
        },
    }


@app.post("/api/sources/inspect")
def inspect_source(payload: dict | None = None) -> dict:
    if payload is None:
        payload = {}
    """Milestone 1 on its own: validate metadata without running the pipeline.

    Returns the accepted/rejected report, the flight extent and warnings. Runs in
    a couple of seconds because it only reads image headers.
    """
    source = payload.get("path")
    if not source:
        raise HTTPException(status_code=400, detail="`path` is required")
    p = Path(source).expanduser()
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"path does not exist: {p}")

    t0 = time.perf_counter()
    result = ingest(p)
    report = result.to_dict()

    footprints = None
    if result.projector is not None and result.accepted:
        from ..geo.footprints import flight_path_geojson, footprint_geojson

        fc = footprint_geojson(result.accepted)
        path_fc = flight_path_geojson(result.accepted)
        for collection in (fc, path_fc):
            for feature in collection["features"]:
                coords = feature["geometry"]["coordinates"]
                rings = coords if feature["geometry"]["type"] == "Polygon" else [coords]
                converted = []
                for ring in rings:
                    converted.append(
                        [list(result.projector.unproject(x, y)) for x, y in ring]
                    )
                feature["geometry"]["coordinates"] = (
                    converted if feature["geometry"]["type"] == "Polygon" else converted[0]
                )
        footprints = {"footprints": fc, "flight_path": path_fc}

    return {
        **report,
        "elapsed_s": time.perf_counter() - t0,
        "suggested_name": p.stem if p.is_file() else p.name,
        "geojson": footprints,
    }


@app.post("/api/sources/upload")
async def upload_source(files: list[UploadFile] = File()) -> dict:
    """Accept browser drag-and-drop of image files, then validate them."""
    files = files or []
    if not files:
        raise HTTPException(status_code=400, detail="no files were uploaded")
    set_id = time.strftime("%Y%m%d-%H%M%S")
    target = config.UPLOAD_DIR / set_id
    target.mkdir(parents=True, exist_ok=True)

    saved, skipped = 0, []
    for f in files:
        name = os.path.basename(f.filename or "image")
        if Path(name).suffix.lower() not in config.SUPPORTED_EXTENSIONS:
            skipped.append(name)
            continue
        dest = target / name
        with dest.open("wb") as fh:
            while chunk := await f.read(1024 * 1024):
                fh.write(chunk)
        saved += 1

    if not saved:
        raise HTTPException(
            status_code=400,
            detail=(
                "no supported image files were uploaded; expected jpg/jpeg/tif/tiff. "
                f"Skipped: {', '.join(skipped[:8])}"
            ),
        )

    result = ingest(target)
    return {
        **result.to_dict(),
        "upload_path": str(target),
        "uploaded": saved,
        "skipped": skipped,
        "suggested_name": f"Upload {set_id}",
        "elapsed_s": None,
    }


@app.get("/api/samples")
def samples() -> dict:
    return {
        "datasets": [
            {**meta, "installed": is_installed(meta["key"]), "path": _sample_path(meta["key"])}
            for meta in list_samples()
        ]
    }


def _sample_path(key: str) -> str | None:
    if not is_installed(key):
        return None
    folder = images_dir(key)
    return str(folder) if folder else None


@app.post("/api/samples/{key}/fetch")
def fetch_sample_dataset(key: str) -> dict:
    logs: list[str] = []

    def progress(message: str) -> None:
        logs.append(message)

    try:
        manifest = fetch_sample(key, progress=progress)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"could not download the sample dataset ({type(exc).__name__}: {exc}). "
                "Manual alternative: clone the repository listed for this dataset into "
                "data/raw/ and point EdgeOrtho at its images folder."
            ),
        ) from exc
    return {**manifest, "log": logs}


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------


@app.post("/api/runs")
def create_run(payload: dict = Body()) -> dict:
    source = payload.get("source")
    if not source:
        raise HTTPException(status_code=400, detail="`source` is required")
    overrides = payload.get("settings") or {}
    settings = config.resolve_settings(
        profile=payload.get("profile") or overrides.get("profile"),
        preset=payload.get("preset") or overrides.get("preset"),
        overrides=overrides,
    )
    name = payload.get("name") or "Untitled run"

    if isinstance(source, str):
        src_path = Path(source).expanduser()
        if not src_path.exists():
            raise HTTPException(status_code=404, detail=f"source does not exist: {src_path}")
        source_arg: str | list[str] = str(src_path)
    elif isinstance(source, list) and source:
        source_arg = [str(Path(s).expanduser()) for s in source]
    else:
        raise HTTPException(status_code=400, detail="`source` must be a path or a list of paths")

    try:
        job = jobs.start(name, source_arg, settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run_id": job.run_id, "status": job.status, "settings": settings.to_dict()}


@app.get("/api/runs")
def list_runs(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    return {"runs": store.list_runs(limit=limit)}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    job = jobs.get(run_id)
    record = store.get_run(run_id, full=True)
    if record is None and job is None:
        raise HTTPException(status_code=404, detail="run not found")
    out: dict = {"run": record}
    if job is not None:
        out["live"] = {
            "status": job.status,
            "events": job.events[-120:],
            "settings": job.settings.to_dict(),
        }
    if record and record.get("report"):
        # the full pair list is large; it is served from /pairs instead
        plan = record["report"].get("plan")
        if isinstance(plan, dict):
            plan.pop("pairs", None)
    return out


@app.get("/api/runs/{run_id}/pairs")
def get_run_pairs(run_id: str) -> dict:
    record = store.get_run(run_id, full=True)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    plan = (record.get("report") or {}).get("plan") or {}
    pairs = plan.get("pairs") or []
    matches = _read_match_table(run_id)
    merged = []
    for p in pairs:
        key = (p["source_id"], p["target_id"])
        merged.append({**p, **(matches.get(key) or {})})
    matched = (record.get("metrics") or {}).get("pairs_matched")
    return {
        "candidate_pairs": len(pairs),
        "matched_pairs": matched,
        "radius_m": plan.get("radius_m"),
        "selection_method": plan.get("selection_method"),
        "reduction_factor": plan.get("reduction_factor"),
        "notes": plan.get("notes") or [],
        "pairs": merged[:400],
    }


def _read_match_table(run_id: str) -> dict:
    """Per-pair match/RANSAC statistics recorded by the match stage."""
    p = config.META_DIR / run_id / "pairs.json"
    if not p.exists():
        return {}
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {(r["source_id"], r["target_id"]): r for r in rows}


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str, delete_files: bool = Query(default=False)) -> dict:
    job = jobs.get(run_id)
    if job and job.status == "running":
        raise HTTPException(status_code=409, detail="cannot delete a run while it is executing")
    existed = store.delete_run(run_id)
    removed = False
    if delete_files:
        out = config.OUTPUT_DIR / run_id
        meta = config.META_DIR / run_id
        for d in (out, meta):
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
                removed = True
    if not existed:
        raise HTTPException(status_code=404, detail="run not found")
    return {"deleted": run_id, "files_removed": removed}


@app.get("/api/runs/{run_id}/events")
def run_events(run_id: str) -> StreamingResponse:
    job = jobs.get(run_id)
    if job is None:
        record = store.get_run(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="run not found")

        def replay_finished():
            yield _sse(
                {
                    "type": "finished",
                    "run_id": run_id,
                    "status": record["status"],
                    "replayed": True,
                }
            )

        return StreamingResponse(replay_finished(), media_type="text/event-stream")

    q, history = job.subscribe()

    def stream():
        try:
            for event in history:
                yield _sse(event)
            if job.status in ("succeeded", "failed"):
                yield _sse({"type": "finished", "run_id": run_id, "status": job.status})
                return
            while True:
                try:
                    event = q.get(timeout=20.0)
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    if job.status in ("succeeded", "failed"):
                        yield _sse({"type": "finished", "run_id": run_id, "status": job.status})
                        return
                    continue
                yield _sse(event)
                if event.get("type") == "finished":
                    return
        finally:
            job.unsubscribe(q)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


# ---------------------------------------------------------------------------
# artifacts and geo data
# ---------------------------------------------------------------------------


def _run_output_dir(run_id: str) -> Path:
    return config.OUTPUT_DIR / run_id


def _require_run(run_id: str) -> dict:
    record = store.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return record


@app.get("/api/runs/{run_id}/preview.png")
def run_preview(run_id: str):
    _require_run(run_id)
    p = _run_output_dir(run_id) / "preview.png"
    if not p.exists():
        raise HTTPException(status_code=404, detail="no preview image for this run")
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/runs/{run_id}/frames/{frame_id}/source.jpg")
def run_frame_source(
    run_id: str,
    frame_id: str,
    max_px: int = Query(default=1280, ge=160, le=2400),
):
    """A bounded JPEG preview of one original frame, for the before/after comparison.

    The raw file is decoded through OpenCV's reduced-resolution flags so opening a
    4000x2250 JPEG to view it does not allocate the full-size buffer. Nothing is written
    to disk and no copy of the raw imagery leaves the machine.
    """
    _require_run(run_id)
    meta_path = config.META_DIR / run_id / "metadata_report.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="no metadata report for this run")
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    frame = next((f for f in payload.get("frames") or [] if f.get("frame_id") == frame_id), None)
    if frame is None:
        raise HTTPException(status_code=404, detail="frame not in this run")
    src = Path(frame.get("path") or "")
    if not src.exists():
        raise HTTPException(status_code=410, detail="the source file is no longer on disk")

    import cv2

    longest = max(frame.get("width") or 0, frame.get("height") or 0)
    reduction = 1
    while reduction < 8 and longest / (reduction * 2) >= max_px:
        reduction *= 2
    flags = {1: cv2.IMREAD_COLOR, 2: cv2.IMREAD_REDUCED_COLOR_2,
             4: cv2.IMREAD_REDUCED_COLOR_4, 8: cv2.IMREAD_REDUCED_COLOR_8}[reduction]
    image = cv2.imread(str(src), flags)
    if image is None:
        raise HTTPException(status_code=415, detail="the source file could not be decoded")
    h, w = image.shape[:2]
    scale = min(1.0, max_px / max(h, w))
    if scale < 1.0:
        image = cv2.resize(
        image, (max(1, round(w * scale)), round(h * scale)),
            interpolation=cv2.INTER_AREA,

        )
    ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    if not ok:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail="JPEG encoding failed")
    return Response(
        content=buf.tobytes(),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "X-Decode-Reduction": str(reduction)},
    )


@app.get("/api/runs/{run_id}/orthomosaic.tif")
def run_geotiff(run_id: str):
    _require_run(run_id)
    p = _run_output_dir(run_id) / "orthomosaic.tif"
    if not p.exists():
        raise HTTPException(status_code=404, detail="no GeoTIFF for this run")
    return FileResponse(
        p, media_type="image/tiff", filename=f"{run_id}_orthomosaic.tif"
    )


@app.get("/api/runs/{run_id}/orthomosaic_cog.tif")
def run_cog(run_id: str):
    _require_run(run_id)
    p = _run_output_dir(run_id) / "orthomosaic_cog.tif"
    if not p.exists():
        raise HTTPException(status_code=404, detail="no COG for this run")
    return FileResponse(p, media_type="image/tiff", filename=f"{run_id}_orthomosaic_cog.tif")


@app.get("/api/runs/{run_id}/report.json")
def run_report(run_id: str):
    _require_run(run_id)
    p = config.META_DIR / run_id / "report.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="no report for this run")
    return FileResponse(p, media_type="application/json", filename=f"{run_id}_report.json")


@app.get("/api/runs/{run_id}/metrics.csv")
def run_metrics_csv(run_id: str):
    _require_run(run_id)
    p = config.META_DIR / run_id / "metrics.csv"
    if not p.exists():
        raise HTTPException(status_code=404, detail="no metrics for this run")
    return FileResponse(p, media_type="text/csv", filename=f"{run_id}_metrics.csv")


@app.get("/api/runs/{run_id}/frames.csv")
def run_frames_csv(run_id: str):
    _require_run(run_id)
    p = config.META_DIR / run_id / "frames.csv"
    if not p.exists():
        raise HTTPException(status_code=404, detail="no frame table for this run")
    return FileResponse(p, media_type="text/csv", filename=f"{run_id}_frames.csv")


@app.get("/api/runs/{run_id}/metadata_report.json")
def run_metadata_report(run_id: str):
    _require_run(run_id)
    p = config.META_DIR / run_id / "metadata_report.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="no metadata report for this run")
    return FileResponse(p, media_type="application/json", filename=f"{run_id}_metadata.json")


@app.get("/api/runs/{run_id}/tiles/{z}/{x}/{y}.png")
def run_tile(run_id: str, z: int, x: int, y: int):
    p = _run_output_dir(run_id) / "tiles" / str(z) / str(x) / f"{y}.png"
    if not p.exists():
        # transparent 1x1 so Leaflet shows nothing rather than a broken tile
        return Response(
            content=_EMPTY_PNG,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "no-store"})


_EMPTY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
    b"\x00\x00IEND\xaeB`\x82"
)


@app.get("/api/runs/{run_id}/tiles.zip")
def run_tiles_zip(run_id: str):
    """Download the generated XYZ tiles as an archive.

    The tiles are already on disk; the zip is assembled per request so the tile tree
    itself stays exactly what the map viewer reads.
    """
    _require_run(run_id)
    tiles = _run_output_dir(run_id) / "tiles"
    members = sorted(tiles.rglob("*.png")) if tiles.exists() else []
    if not members:
        raise HTTPException(status_code=404, detail="no XYZ tiles for this run")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for p in members:
            archive.write(p, p.relative_to(tiles).as_posix())
    payload = buf.getvalue()
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{run_id}_xyz_tiles.zip"',
            "Content-Length": str(len(payload)),
            "X-Tile-Count": str(len(members)),
        },
    )


@app.get("/api/runs/{run_id}/geojson")
def run_geojson(run_id: str) -> dict:
    """Image footprints and the flight path, reprojected to WGS84 for Leaflet."""
    record = _require_run(run_id)
    meta_path = config.META_DIR / run_id / "metadata_report.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="no metadata report for this run")
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    epsg = ((record.get("report") or {}).get("canvas") or {}).get("crs_epsg")
    frames = payload.get("frames") or []
    return _frames_to_geojson(frames, epsg, record)


def _frames_to_geojson(frames: list[dict], epsg: int | None, record: dict) -> dict:
    from pyproj import Transformer

    to_wgs = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True) if epsg else None

    def conv(x: float, y: float) -> list[float]:
        if to_wgs is None:
            return [float(x), float(y)]
        lon, lat = to_wgs.transform(float(x), float(y))
        return [lon, lat]

    features = []
    path_points = []
    for f in frames:
        if not f.get("accepted") or f.get("projected_x") is None:
            continue
        cx, cy = float(f["projected_x"]), float(f["projected_y"])
        w = f.get("footprint_w_m")
        h = f.get("footprint_h_m")
        yaw = f.get("yaw_deg") or 0.0
        path_points.append(conv(cx, cy))
        if w and h:
            import math

            rad = math.radians(yaw)
            fx, fy = math.sin(rad), math.cos(rad)
            rx, ry = math.cos(rad), -math.sin(rad)
            hw, hh = w / 2.0, h / 2.0
            corners = []
            for r, fq in ((-1, 1), (1, 1), (1, -1), (-1, -1)):
                corners.append(conv(cx + r * hw * rx + fq * hh * fx, cy + r * hw * ry + fq * hh * fy))
            corners.append(corners[0])
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "kind": "footprint",
                        "frame_id": f.get("frame_id"),
                        "filename": f.get("filename"),
                        "yaw_deg": yaw,
                        "gsd_m": f.get("gsd_m"),
                        "altitude_m": f.get("altitude_m"),
                        "captured_at": f.get("captured_at"),
                    },
                    "geometry": {"type": "Polygon", "coordinates": [corners]},
                }
            )
    if len(path_points) >= 2:
        features.append(
            {
                "type": "Feature",
                "properties": {"kind": "flight_path", "frames": len(path_points)},
                "geometry": {"type": "LineString", "coordinates": path_points},
            }
        )

    output = record.get("output") or {}
    bounds = output.get("bounds_wgs84")
    return {
        "type": "FeatureCollection",
        "properties": {
            "crs": output.get("crs"),
            "crs_name": output.get("crs_name"),
            "bounds_wgs84": bounds,
            "output_kind": output.get("kind"),
            "tiles": bool(output.get("tiles_dir")),
            "tile_zoom": [output.get("min_zoom"), output.get("max_zoom")],
        },
        "features": features,
    }


# ---------------------------------------------------------------------------
# performance lab
# ---------------------------------------------------------------------------


@app.get("/api/performance")
def performance() -> dict:
    records = store.performance_records()
    return {
        "records": records,
        "count": len(records),
        "bandwidth_rates_mbps": list(BANDWIDTH_TEST_MBPS),
        "notes": [
            "Every value comes from a completed run on this machine. Missing measurements are "
            "returned as null rather than as zero.",
            "Constrained profiles emulate CPU and RAM limits on this host; they are not physical "
            "Raspberry Pi or Jetson measurements.",
            "Bandwidth transfer times use measured byte counts and the formula "
            "transfer_seconds = bytes * 8 / bits_per_second.",
        ],
    }


@app.get("/api/performance/export")
def performance_export(fmt: str = Query(default="json", pattern="^(json|csv)$")):
    records = store.performance_records()
    if fmt == "json":
        return JSONResponse(
            {"records": records, "exported_at": time.time(), "version": VERSION},
            headers={"Content-Disposition": 'attachment; filename="edgeortho_performance.json"'},
        )
    import csv
    import io

    fields: list[str] = []
    for r in records:
        for k in r:
            if k not in fields and not isinstance(r[k], (dict, list)):
                fields.append(k)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for r in records:
        writer.writerow(r)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="edgeortho_performance.csv"'},
    )


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------


@app.get("/api/settings")
def get_settings() -> dict:
    saved = store.get_settings()
    return {
        "settings": {
            **config.PipelineSettings().to_dict(),
            **(saved.get("pipeline") or {}),
        },
        "saved": saved,
    }


@app.put("/api/settings")
def put_settings(payload: dict = Body()) -> dict:
    pipeline = payload.get("pipeline")
    if not isinstance(pipeline, dict):
        raise HTTPException(status_code=400, detail="`pipeline` object is required")
    validated = config.PipelineSettings.from_dict(pipeline)
    return store.put_settings({"pipeline": validated.to_dict()})


# ---------------------------------------------------------------------------
# static frontend (when built)
# ---------------------------------------------------------------------------


def mount_static() -> None:
    """Serve the built frontend if it exists, so `edgeortho serve` is one command."""
    dist = config.PROJECT_ROOT / "frontend" / "dist"
    if not dist.exists():
        return
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")


mount_static()
