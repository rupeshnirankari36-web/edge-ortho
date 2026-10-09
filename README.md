# GEOAI 01 — Edge Processing of High-Resolution Drone Imagery

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

**Team:** Abhyuday, Naman, Rupesh  
**Project:** Local, edge-optimized 2D drone orthomosaic pipeline  
**Primary Output:** Georeferenced GeoTIFF / Cloud-Optimized GeoTIFF (COG), XYZ Tiles, Metrics & Web Viewers  
**Repository:** `edge-ortho`

---

## Overview

`edge-ortho` is an edge-first, memory-bounded 2D drone photogrammetry and orthomosaicing pipeline designed to run on constrained hardware (Raspberry Pi 4/5, Jetson Orin/Xavier, or field laptops) without cloud upload bandwidth bottlenecks.

### Key Capabilities
- **GPS-Guided Ingestion:** Reads EXIF/XMP, converts WGS84 to local projected CRS (UTM), estimates GSD and flight heading.
- **Neighbor Graph Matching:** Replaces $O(N^2)$ all-pairs matching with a spatial $k$-d tree graph ($O(N \log N)$), dramatically lowering edge compute load.
- **Robust Multi-Feature Registration:** Supports ORB, AKAZE, and SIFT with ratio testing and RANSAC geometric estimation (Similarity, Affine, and Homography).
- **Global Pose Graph Optimization:** Solves global frame placement using Levenberg-Marquardt / Truncated Loss robust least squares, incorporating visual matches with weak GPS priors.
- **Bounded-Memory Tile Composition:** Warps, exposure-compensates, and blends frames chunk-by-chunk onto 2048x2048 tiles—preventing out-of-memory (OOM) crashes even for 200+ image surveys.
- **Full Georeferencing & Export:** Produces standard georeferenced GeoTIFF, Cloud-Optimized GeoTIFF (COG), and standard XYZ web map tiles.
- **Dual Web Viewers & GIS Integration:** Ready for Leaflet, Mapbox GL JS, and QGIS desktop validation.
- **Continuous Edge Telemetry:** Monitors real-time CPU %, RSS RAM (MB), disk I/O, latency per stage, and outputs bandwidth transfer comparisons.

---

## Quickstart

### 1. Installation

```bash
git clone <repo-url>
cd edge-ortho
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate

# On Windows:
.\.venv\Scripts\activate

pip install -e ".[dev]"
```

### 2. Run Single-Command Pipeline

```bash
edge-ortho run --input data/raw/sample_drone_survey/ --out outputs/survey_run --profile pi-class --preset balanced
```

### 3. Launch Live Watch Mode

```bash
edge-ortho watch --input data/incoming_stream/ --out outputs/live_run --profile pi-class
```

### 4. Interactive Web Viewers

After processing, open the interactive web viewers:
- Leaflet Viewer: `viewer/leaflet/index.html?manifest=../../outputs/survey_run/manifest.json`
- Mapbox Viewer: `viewer/mapbox/index.html?manifest=../../outputs/survey_run/manifest.json`

---

## Edge Hardware Profiles

| Profile | Target Hardware | Max CPUs | RAM Limit | Primary Matcher | Transform Model |
|---|---|---:|---:|---|---|
| `pi-lite` | Raspberry Pi 4 (2 GB) | 2 | 2 GB | ORB | Similarity |
| `pi-class` | Raspberry Pi 4/5 (4 GB) | 4 | 4 GB | AKAZE | Affine |
| `jetson-class` | Jetson Orin Nano (8 GB) | 6 | 8 GB | SIFT | Homography |
| `laptop` | Host Workstation | Host Default | Host Default | SIFT | Affine |
