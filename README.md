# EdgeOrtho — Local Edge Drone Mapping

**EdgeOrtho** converts overlapping, geotagged drone images into a georeferenced 2D orthomosaic entirely on-device. No cloud upload of raw imagery. Designed for constrained edge hardware (laptop, Raspberry Pi-class, Jetson-class).

---

## Quick Start

### 1 – Backend

```powershell
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\python server.py
```
API at http://127.0.0.1:8000 · Docs at http://127.0.0.1:8000/docs

### 2 – Frontend

```powershell
cd dashboard
npm install
npm run dev
```
Open http://localhost:5173

---

## Architecture

```
edge-ortho/
+-- server.py                   # Uvicorn entry point
+-- src/edge_ortho/
¦   +-- api/main.py             # FastAPI endpoints
¦   +-- ingest/reader.py        # EXIF GPS extraction + readability
¦   +-- ingest/neighbours.py    # Haversine GPS proximity graph
¦   +-- align/matcher.py        # ORB + Lowe ratio + RANSAC affine
¦   +-- compose/mosaic.py       # Memory-bounded mosaic + GeoTIFF
¦   +-- pipeline.py             # Orchestrator, metrics, stage tracking
+-- dashboard/src/pages/        # React + Vite + Tailwind frontend
+-- tests/test_pipeline.py      # 21 unit tests (all passing)
```

### Pipeline Stages

Ingest ? Validate GPS ? Plan Neighbours ? Match Features ? Align ? Compose Tiles ? Georeference ? Export

| Stage | What happens |
|---|---|
| Ingest | Discover JPEG/TIFF, read via OpenCV, parse EXIF GPS via exifread |
| Validate GPS | Reject missing coords. Require >= 2 GPS images |
| Plan Neighbours | Haversine graph (default 120m radius, max 6 neighbours). Avoids O(n2) exhaustive matching |
| Match Features | Downscale to ~0.6 MP. ORB 2000 kp. BFMatcher + Lowe ratio 0.75. RANSAC affine |
| Align | estimateAffinePartial2D. BFS propagation from reference image |
| Compose Tiles | Canvas-bounded warpPerspective. 8192 px safety cap |
| Georeference | GPS centres -> bounding-box affine -> GeoTIFF EPSG:4326 via rasterio |
| Export | mosaic.jpg + mosaic_georef.tif + metrics JSON |

WARNING: EXIF GPS image centres alone do not establish survey-grade accuracy.
Validated georeferencing requires Ground Control Points (GCPs).

---

## Sample Dataset

### Option A - OpenDroneMap sample
git clone https://github.com/OpenDroneMap/odm_data_aukerman
Upload images from odm_data_aukerman/images/ via New Project page.

### Option B - Your own geotagged drone images
Requirements: embedded GPS EXIF (GPSLatitude, GPSLongitude), JPEG/TIFF, >= 2 frames with < 120m GPS separation.

---

## Tests

.\venv\Scripts\python -m pytest tests/ -v
Result: 21 passed in ~1.7s

---

## API Reference

GET    /api/health                       Health + RSS
GET    /api/projects                     List projects
POST   /api/projects                     Create project
GET    /api/projects/{id}                Get project + pipeline state
DELETE /api/projects/{id}                Delete project
POST   /api/projects/{id}/images         Upload + ingest images
GET    /api/projects/{id}/gps            GPS points
GET    /api/projects/{id}/ingest-report  Per-image validation
POST   /api/projects/{id}/process        Start pipeline (background)
GET    /api/projects/{id}/pipeline-state Full diagnostics JSON
GET    /api/projects/{id}/mosaic         Mosaic JPEG download
GET    /api/projects/{id}/geotiff        GeoTIFF download
GET    /api/projects/{id}/metrics-report Performance report JSON

---

## Implemented

- Image ingest with EXIF GPS extraction
- Readability validation (OpenCV)
- Per-image acceptance/rejection report
- Haversine GPS proximity graph (O(n*k) not O(n2))
- ORB feature extraction at configurable resolution
- Lowe ratio filtering + RANSAC affine estimation
- BFS-based global transform propagation
- Memory-bounded mosaic composition (8192 px canvas cap)
- GeoTIFF output via rasterio
- Measured peak RAM, wall-clock time, per-stage timing
- Bandwidth estimates (1/5/20 Mbps) from measured byte counts
- Project persistence (JSON, no DB dependency)
- React + Tailwind frontend with Projects, New Project, Workspace, Map, Results, Performance Lab
- Interactive Leaflet map with GPS flight-path overlay
- 21 unit tests all passing

## Known Limitations / Future Work

- GCP-based georeferencing: Planned
- Homography comparison: Planned (affine only for MVP)
- COG + XYZ tiles: Planned (requires gdal_translate)
- GPU acceleration (Jetson): Planned
- Actual Pi/Jetson benchmark: Must run on target hardware
- Survey-grade accuracy: Cannot be claimed without GCPs
- Settings UI: Placeholder only in this release

---

## Demo Script

1. .\venv\Scripts\python server.py
2. cd dashboard ; npm run dev
3. Open http://localhost:5173
4. Click "New Mapping Project"
5. Select geotagged drone images, click "Create & Ingest"
6. In project view click "Start Pipeline"
7. Watch stage progress update live (2.5s polling)
8. Map Viewer tab shows GPS flight path
9. Results & Export shows mosaic + GeoTIFF download
10. Download Metrics JSON for performance report

