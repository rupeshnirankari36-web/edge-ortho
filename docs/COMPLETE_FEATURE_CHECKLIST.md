# EdgeOrtho Complete Feature Checklist

Generated from the GEOAI 01 project brief and the merged implementation on 2026-10-09.

## Status definitions

- **PASS** — implemented and verified locally with an automated test or smoke check.
- **PARTIAL** — implementation exists and some checks pass, but required real-dataset, hardware, visual, or evidence validation is still missing.
- **OPEN** — required implementation or evidence artifact is not present in this checkout.

## Validation run summary

| Check | Result | Evidence / command |
|---|---:|---|
| Full automated test suite | **PASS** | `python3 -m pytest -q` → **50 passed** |
| Ruff lint | **PASS** | `python3 -m ruff check src tests` |
| Python compilation/imports | **PASS** | `python3 -m compileall -q src`; package imports successfully |
| CLI registration | **PASS** | `edge-ortho --help` lists `run`, `watch`, `verify-dataset`, `compare-transforms` |
| Dataset verifier smoke test | **PASS** | `edge-ortho verify-dataset data/raw --csv ...` runs successfully on empty raw folder |
| FastAPI health/projects smoke test | **PASS** | `/api/health` → HTTP 200; `/api/projects` → HTTP 200; 17 routes registered |
| Synthetic end-to-end GeoTIFF/COG/tile/report run | **PASS** | `tests/test_pipeline.py` and related export tests |
| Real ODM dataset run | **OPEN** | No downloaded ODM dataset or saved run output in this checkout |
| 200+ image stress run | **OPEN** | No 200+ image output, resource log, or report present |
| QGIS visual validation | **OPEN** | No QGIS screenshot/inspection artifact present |
| Leaflet visual validation | **OPEN** | `viewer/leaflet/index.html` is referenced but absent |
| Mapbox visual validation | **OPEN** | `viewer/mapbox/index.html` is referenced but absent |

## Requirement-to-evidence checklist

| ID | Requirement | Implementation status | Evidence status | Final status |
|---|---|---|---|---:|
| R1 | Local edge processing | Profiles, bounded composition, Docker files, CPU/RAM monitor exist | No real constrained Docker/device run saved | **PARTIAL** |
| R2 | Automatic ingestion | EXIF ingestion, CLI `run`, and `watch` command exist; API upload exists | CLI/verifier smoke passes; watch-folder live run not evidenced | **PARTIAL** |
| R3 | Feature matching | ORB, AKAZE, SIFT, ratio filtering, GPS-neighbour restriction, RANSAC implemented | Synthetic matcher tests pass; no real ODM pair statistics saved | **PARTIAL** |
| R4 | Perspective alignment/blending | Similarity/affine/homography paths, exposure compensation, feather/multiband helpers exist | Synthetic end-to-end test passes; required two-real-dataset comparison absent | **PARTIAL** |
| R5 | Georeferenced GeoTIFF/COG | Rasterio writer, CRS/transform, COG conversion, nodata/alpha handling exist | Synthetic GeoTIFF/COG tests pass; QGIS inspection absent | **PARTIAL** |
| R6 | QGIS, Leaflet, Mapbox | XYZ tile generator exists and report references viewers | Viewer source files and visual validation artifacts are absent | **OPEN** |
| R7 | CPU/RAM/latency logging | `psutil` monitor, stage timings, CSV/JSON reports exist | Synthetic output assertions pass; no saved real run metrics bundle | **PARTIAL** |
| R8 | ODM and Esri dataset verification | Dataset documentation and verifier command exist | No downloaded/accepted/rejected dataset metadata artifact | **OPEN** |
| R9 | Bandwidth motivation | Bandwidth calculation/report code exists | Formula tests pass; no measured raw/output table from a real dataset | **PARTIAL** |
| R10 | Edge optimization | Downscaled matching, KD-tree neighbour graph, bounded tile composition implemented | Unit tests pass; RAM-vs-image-count graph absent | **PARTIAL** |
| R11 | Hundreds of frames | Pipeline is designed for 200+ images and profiles exist | Mandatory 200+ image run evidence absent | **OPEN** |
| R12 | Quickly / latency targets | First-tile and total-latency fields are implemented | Synthetic latency exists; no benchmark target/mean/spread report | **PARTIAL** |

## Feature-level checklist

### Ingestion and planning

- [x] Discover JPEG/TIFF frames.
- [x] Read GPS EXIF metadata.
- [x] Validate readable files and GPS presence.
- [x] Record rejection reasons.
- [x] Convert GPS to projected UTM coordinates.
- [x] Estimate GSD.
- [x] Derive heading when possible.
- [x] Build a capped GPS neighbour graph with KD-tree support.
- [ ] Validate against at least one real ODM and one Esri sample.

### Matching and alignment

- [x] ORB detector.
- [x] AKAZE detector.
- [x] SIFT detector.
- [x] Downscale matching images to bounded working resolution.
- [x] Lowe ratio filtering.
- [x] RANSAC inlier filtering.
- [x] Similarity/affine alignment path.
- [x] Homography alignment path using RANSAC.
- [x] Global robust solve with GPS prior.
- [x] GPS fallback for weak/failed visual pairs.
- [ ] Produce affine-vs-homography comparison on two real datasets.
- [ ] Save pair statistics, inlier ratios, and reprojection-error evidence from a real run.

### Composition and geospatial export

- [x] Compute canvas bounds.
- [x] Compose tile-by-tile with bounded working memory.
- [x] Exposure compensation helper.
- [x] Feather blending.
- [x] Optional multiband blending configuration/path.
- [x] North-up georeferenced GeoTIFF.
- [x] COG conversion.
- [x] XYZ raster tile generation.
- [x] Synthetic raster, CRS, COG, and manifest tests.
- [ ] Validate visual placement in QGIS with screenshot.
- [ ] Validate tile placement in a web viewer.

### Monitoring and reporting

- [x] Total latency.
- [x] Per-stage latency.
- [x] Time to first tile.
- [x] Frames processed/accepted/rejected.
- [x] Throughput fields.
- [x] Average/peak CPU fields.
- [x] Average/peak RSS RAM fields.
- [x] Disk read/write fields.
- [x] Temperature/throttle hooks where platform tools exist.
- [x] Input/output byte counts.
- [x] Match, inlier, ratio, and reprojection fields.
- [x] CRS, bounds, pixel size, and raster dimensions.
- [x] Run profile, preset, platform, and Git metadata fields.
- [x] JSON, CSV, Markdown, chart, and manifest output paths.
- [ ] Save a real-dataset evidence bundle.
- [ ] Generate the required bandwidth table at 1/5/20 Mbps from measured bytes.
- [ ] Generate RAM-vs-image-count graph at 20/40/80/160/200+ frames.

### CLI and API

- [x] `edge-ortho run`.
- [x] `edge-ortho watch`.
- [x] `edge-ortho verify-dataset`.
- [x] `edge-ortho compare-transforms`.
- [x] API project creation/listing.
- [x] API image upload.
- [x] API GPS and ingest-report endpoints.
- [x] API background processing adapter.
- [x] API pipeline-state and metrics endpoints.
- [x] API GeoTIFF/mosaic result endpoints.
- [x] API health endpoint.
- [ ] Full upload → process → download API integration test with geotagged images.
- [ ] Live watch-folder acceptance run.

### Packaging and operations

- [x] `pyproject.toml` package metadata.
- [x] Development dependencies and editable install.
- [x] Dockerfile and Docker Compose definitions.
- [x] Hardware profiles: laptop, pi-lite, pi-class, jetson-class.
- [x] Presets: fast, balanced, quality.
- [x] GitHub Actions CI workflow exists.
- [x] MIT license.
- [x] Raw imagery and generated outputs ignored by Git.
- [ ] Execute Docker profile sweep and save results.
- [ ] Run ODM comparison benchmark.
- [ ] Run public ARM64 CI/device check if available.

## Required remaining work to reach full brief completion

1. Download and verify a real ODM smoke dataset using `edge-ortho verify-dataset`.
2. Run the complete pipeline on `aukerman` and `toledo` or equivalent accepted datasets.
3. Run the mandatory `wietrznia` or `waterbury` 200+ image stress dataset.
4. Save `report.json`, `report.md`, `metrics.csv`, resource chart, manifest, tile counts, and bandwidth table for each key run.
5. Perform the 20/40/80/160/200+ RAM scaling experiment.
6. Perform affine-vs-homography comparisons on at least two real datasets.
7. Add and smoke-test `viewer/leaflet/index.html`.
8. Add and smoke-test `viewer/mapbox/index.html` with runtime-only token configuration.
9. Perform QGIS placement/CRS inspection and save a screenshot or exact limitation record.
10. Run and document ODM planar comparison and Esri metadata acceptance/rejection.
11. Add a full API upload → process → artifact download integration test.
12. Publish the resulting evidence index and update the traceability matrix from **Open** to **Pass** only when artifacts exist.

## Reproduction commands

```bash
# Install
python3 -m pip install -e '.[dev]'

# Automated implementation checks
python3 -m pytest -q
python3 -m ruff check src tests
python3 -m compileall -q src

# CLI checks
edge-ortho --help
edge-ortho verify-dataset data/raw --csv /tmp/dataset-meta.csv

# Real run template
edge-ortho run \
  --input data/raw/<accepted-dataset>/images \
  --out outputs/<dataset>-laptop \
  --profile laptop \
  --preset balanced
```
