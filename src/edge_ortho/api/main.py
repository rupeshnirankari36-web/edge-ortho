"""
EdgeOrtho – FastAPI backend.

Provides endpoints for project CRUD, image upload, pipeline execution,
and result retrieval. Raw imagery stays local; no cloud uploads.
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from typing import Any, List, Optional

import psutil
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="EdgeOrtho Local API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
PROJECTS_DIR = os.path.join(BASE_DIR, "data", "projects")
os.makedirs(PROJECTS_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proj_dir(project_id: str) -> str:
    return os.path.join(PROJECTS_DIR, project_id)


def _read_meta(project_id: str) -> Optional[dict]:
    path = os.path.join(_proj_dir(project_id), "metadata.json")
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def _write_meta(project_id: str, meta: dict) -> None:
    os.makedirs(_proj_dir(project_id), exist_ok=True)
    path = os.path.join(_proj_dir(project_id), "metadata.json")
    with open(path, "w") as f:
        json.dump(meta, f, indent=2, default=str)


def _read_pipeline_state(project_id: str) -> Optional[dict]:
    path = os.path.join(_proj_dir(project_id), "pipeline_state.json")
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


# ---------------------------------------------------------------------------
# Background pipeline runner
# ---------------------------------------------------------------------------

def _run_pipeline_bg(project_id: str) -> None:
    """Run in background thread. Updates metadata.json on completion."""
    try:
        from ...edge_ortho.pipeline import run_pipeline  # type: ignore[import]
    except ImportError:
        # Try direct import when running from src root
        import sys, importlib
        sys.path.insert(0, os.path.join(BASE_DIR, "src"))
        from edge_ortho.pipeline import run_pipeline  # type: ignore[import]

    proj_dir = _proj_dir(project_id)
    raw_dir = os.path.join(proj_dir, "raw")

    meta = _read_meta(project_id) or {}
    meta["status"] = "processing"
    _write_meta(project_id, meta)

    try:
        result = run_pipeline(proj_dir, raw_dir)
        meta = _read_meta(project_id) or {}
        meta["status"] = "completed" if not result.get("error") else "error"
        meta["pipeline_error"] = result.get("error")
        meta["metrics"] = result.get("metrics", {})
        meta["stages"] = result.get("stages", {})
        meta["diagnostics"] = result.get("diagnostics", {})
        _write_meta(project_id, meta)
    except Exception as exc:
        meta = _read_meta(project_id) or {}
        meta["status"] = "error"
        meta["pipeline_error"] = str(exc)
        _write_meta(project_id, meta)


# ---------------------------------------------------------------------------
# Routes – Projects
# ---------------------------------------------------------------------------

@app.post("/api/projects")
async def create_project(name: str = Form(...)):
    project_id = str(uuid.uuid4())
    meta = {
        "id": project_id,
        "name": name,
        "status": "created",
        "created_at": time.time(),
        "image_count": 0,
        "valid_images": 0,
        "metrics": {},
        "stages": {},
        "diagnostics": {},
    }
    _write_meta(project_id, meta)
    return {"id": project_id, "name": name}


@app.get("/api/projects")
def list_projects():
    projects = []
    if os.path.exists(PROJECTS_DIR):
        for pid in os.listdir(PROJECTS_DIR):
            if not os.path.isdir(_proj_dir(pid)):
                continue
            m = _read_meta(pid)
            if m:
                projects.append(m)
    return sorted(projects, key=lambda x: x.get("created_at", 0), reverse=True)


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    m = _read_meta(project_id)
    if not m:
        raise HTTPException(status_code=404, detail="Project not found")
    # Merge latest pipeline state if available
    ps = _read_pipeline_state(project_id)
    if ps:
        m["stages"] = ps.get("stages", m.get("stages", {}))
        m["metrics"] = ps.get("metrics", m.get("metrics", {}))
        m["diagnostics"] = ps.get("diagnostics", m.get("diagnostics", {}))
    return m


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    pd = _proj_dir(project_id)
    if not os.path.exists(pd):
        raise HTTPException(status_code=404, detail="Project not found")
    shutil.rmtree(pd)
    return {"deleted": project_id}


# ---------------------------------------------------------------------------
# Routes – Image upload / ingest
# ---------------------------------------------------------------------------

@app.post("/api/projects/{project_id}/images")
async def upload_images(project_id: str, files: List[UploadFile] = File(...)):
    m = _read_meta(project_id)
    if not m:
        raise HTTPException(status_code=404, detail="Project not found")

    raw_dir = os.path.join(_proj_dir(project_id), "raw")
    os.makedirs(raw_dir, exist_ok=True)

    saved = []
    for file in files:
        safe_name = os.path.basename(file.filename or "image.jpg")
        dest = os.path.join(raw_dir, safe_name)
        with open(dest, "wb") as out:
            shutil.copyfileobj(file.file, out)
        saved.append(safe_name)

    # Run fast ingest (metadata only, no heavy processing)
    import sys
    sys.path.insert(0, os.path.join(BASE_DIR, "src"))
    from edge_ortho.ingest.reader import ingest_folder

    t0 = time.perf_counter()
    images = ingest_folder(raw_dir)
    ingest_time = time.perf_counter() - t0

    gps_images = [img for img in images if img.has_gps]
    valid_images = [img for img in images if img.readable]

    gps_data = [
        {"filename": img.filename, "lat": img.lat, "lon": img.lon, "alt": img.alt or 0.0}
        for img in gps_images
    ]
    with open(os.path.join(_proj_dir(project_id), "gps.json"), "w") as f:
        json.dump(gps_data, f)

    ingest_report = [
        {
            "filename": img.filename,
            "readable": img.readable,
            "has_gps": img.has_gps,
            "width": img.width,
            "height": img.height,
            "file_bytes": img.file_bytes,
            "rejection_reason": img.rejection_reason,
        }
        for img in images
    ]
    with open(os.path.join(_proj_dir(project_id), "ingest_report.json"), "w") as f:
        json.dump(ingest_report, f)

    m["image_count"] = len(images)
    m["valid_images"] = len(gps_images)
    m["status"] = "ready_for_processing" if len(gps_images) >= 2 else (
        "error" if not valid_images else "warning_no_gps"
    )
    m["stages"]["ingest"] = "completed"
    m["diagnostics"]["ingest"] = {
        "total_found": len(images),
        "readable": len(valid_images),
        "with_gps": len(gps_images),
        "elapsed_s": round(ingest_time, 3),
    }
    _write_meta(project_id, m)

    return {
        "saved": len(saved),
        "readable": len(valid_images),
        "with_gps": len(gps_images),
        "status": m["status"],
    }


@app.get("/api/projects/{project_id}/gps")
def get_gps(project_id: str):
    path = os.path.join(_proj_dir(project_id), "gps.json")
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return []


@app.get("/api/projects/{project_id}/ingest-report")
def get_ingest_report(project_id: str):
    path = os.path.join(_proj_dir(project_id), "ingest_report.json")
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return []


# ---------------------------------------------------------------------------
# Routes – Processing
# ---------------------------------------------------------------------------

@app.post("/api/projects/{project_id}/process")
def start_processing(project_id: str, background_tasks: BackgroundTasks):
    m = _read_meta(project_id)
    if not m:
        raise HTTPException(status_code=404, detail="Project not found")
    if m.get("status") == "processing":
        return {"message": "Already processing"}

    m["status"] = "processing"
    _write_meta(project_id, m)
    background_tasks.add_task(_run_pipeline_bg, project_id)
    return {"message": "Processing started", "project_id": project_id}


@app.get("/api/projects/{project_id}/pipeline-state")
def pipeline_state(project_id: str):
    ps = _read_pipeline_state(project_id)
    if not ps:
        raise HTTPException(status_code=404, detail="Pipeline state not found")
    return ps


# ---------------------------------------------------------------------------
# Routes – Results / Outputs
# ---------------------------------------------------------------------------

@app.get("/api/projects/{project_id}/mosaic")
def get_mosaic(project_id: str):
    """Return the generated mosaic JPEG if available."""
    path = os.path.join(_proj_dir(project_id), "output", "mosaic.jpg")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Mosaic not available yet")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/projects/{project_id}/geotiff")
def get_geotiff(project_id: str):
    path = os.path.join(_proj_dir(project_id), "output", "mosaic_georef.tif")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="GeoTIFF not available")
    return FileResponse(path, media_type="image/tiff", filename="mosaic_georef.tif")


@app.get("/api/projects/{project_id}/metrics-report")
def metrics_report(project_id: str):
    """Return downloadable JSON metrics report."""
    m = _read_meta(project_id)
    ps = _read_pipeline_state(project_id)
    if not m:
        raise HTTPException(status_code=404, detail="Project not found")
    report = {
        "project_id": project_id,
        "project_name": m.get("name"),
        "generated_at": time.time(),
        "metrics": ps.get("metrics", {}) if ps else m.get("metrics", {}),
        "diagnostics": ps.get("diagnostics", {}) if ps else m.get("diagnostics", {}),
        "stages": ps.get("stages", {}) if ps else m.get("stages", {}),
        "note": (
            "All metrics are measured from this local processing run. "
            "Bandwidth estimates are calculated from actual byte counts. "
            "No results are simulated or approximated."
        ),
    }
    return report


# ---------------------------------------------------------------------------
# Static files for mosaic serving
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok", "process_rss_mb": round(psutil.Process().memory_info().rss / 1e6, 1)}
