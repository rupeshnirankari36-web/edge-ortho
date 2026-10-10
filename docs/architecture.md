# EdgeOrtho — architecture and processing algorithm

## System boundary

EdgeOrtho is a **single-machine local pipeline with a local HTTP API**. The
backend runs on the same machine as the imagery, reads the images in place from
disk, and serves the results to a React frontend. No request leaves the host.
No raw imagery is ever uploaded anywhere.

The product boundary is therefore **local-first by default**, not "cloud with a
privacy promise". Against the GEOAI 01 brief's privacy and bandwidth constraints
this is the primary differentiator: the raw imagery costs nothing to transfer
because it never leaves the device.

## Runtime

- **Backend:** Python 3.11+/3.12, FastAPI, served by uvicorn.
- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS, Leaflet for the map.
- **Store:** a single SQLite file (`data/edgeortho.sqlite3`) holds run records,
  per-stage counters, settings and the performance ledger.
- **Path layout:**
  - `data/meta/<run_id>/` — metadata report, frame table, pair statistics,
    metrics CSV, run report JSON.
  - `data/raw/<dataset>/` — downloaded sample datasets (git-ignored).
  - `outputs/<run_id>/` — GeoTIFF, COG, XYZ tiles, mosaic preview.
  - `scripts/` — command-line utilities including the end-to-end checker.
  - `tests/` — pytest suite exercising the real pipeline on synthetic imagery.

## Module map

```
edge_ortho/
  config.py            runtime paths, PipelineSettings, presets, constants
  contracts.py         FrameRecord, GlobalPose, StageRecord, bandwidth maths
  profiles.py          HardwareProfile, ResourceLimiter, MemoryCeilingExceeded
  storage.py           RunStore (SQLite) for runs, pairs, settings, performance
  sample.py            sample dataset acquisition (OpenDroneMap public datasets)
  cli.py               command-line entry point: run, inspect, serve, samples, profiles
  api/
    app.py             FastAPI routes: system, sources, runs, artifacts, performance, settings
    jobs.py            JobManager: single-run concurrency, Server-Sent Events fan-out
  ingest/
    discovery.py       file discovery (supported extensions, skipped unsupported)
    exif.py            EXIF + XMP extraction, GPS/altitude/yaw, camera model, GSD precursors
    validate.py        frame validation, projection, dataset warnings, suitability
  geo/
    footprints.py      image footprint polygons, overlap fraction
    projection.py      UTM projection, ground sampling distance from metadata
    raster.py          tiled GeoTIFF writer, COG conversion, overviews, XYZ tiles, preview
  plan/
    neighbours.py      KD-tree candidate selection, overlap gating, link cap
  features/
    matching.py        matching copy, ORB/AKAZE detector, k-NN, Lowe ratio, status codes
  align/
    transform.py       pair affine/homography fit, RANSAC, inliers, reprojection error
    global_align.py    global similarity solve, heading resolution, GPS anchor,
                       homography comparison, output canvas geometry
  compose/
    mosaic.py          tile-by-tile stream composer, decode cache, exposure gains
  monitor/
    resources.py       ResourceSampler (psutil RSS/CPU/disk), stage_timer, MemoryGuard
  pipeline.py         orchestrates the eight stages, builds the report and metrics
```

## Processing algorithm, stage by stage

### 1. Ingest (discovery)

`discover_images` walks the source (recursively by default) and collects
supported extensions. Unsupported files are listed in `skipped_unsupported`;
they are not silently dropped. A single-file source is supported; a directory
is supported. The result is a list of `Path`s that feed the next stage.

### 2. Validate GPS (validation)

For every discovered file, `read_image_metadata` does:

- **header dimensions** via PIL `Image.open` (no full decode).
- **EXIF GPS** (latitude, longitude) via `piexif`; **EXIF altitude** (above
  sea level, signed by `GPSAltitudeRef`); **EXIF focal length** (35mm equiv
  and/or physical); **EXIF camera make/model**.
- **XMP** from the file head (DJI packet): `RelativeAltitude`, `AbsoluteAltitude`,
  `GimbalYawDegree`, `GimbalPitchDegree`, and XMP GPS. The XMP relative altitude
  is the preferred AGL reading; absolute altitude is flagged as approximate.
- **GSD precursor** from altitude, focal length, sensor width, and image
  dimensions, with the 35mm-equivalent as the preferred input.

Each `FrameRecord` is accepted only if it has valid GPS within range, a
decodable image, and a positive height. Frames without GPS are rejected as
`missing_gps`. Null island (0,0) is rejected as `invalid_gps`. Empty files are
rejected as `zero_size`. Corrupt files are reported as `decode_failed`.

A projector is chosen for the mean GPS of accepted frames, and every accepted
frame is projected to projected coordinates. Altitude, yaw, and focus metadata
feed downstream geometry and heading.

### 3. Plan neighbours (planning)

A `cKDTree` is built on the projected centres. The candidate radius is
adaptive: it is scaled from the **measured footprint diagonal**, not a fixed
constant. This is the central edge claim from the brief: using GPS to bound
comparisons instead of all-pairs.

Where footprint polygons are available, each candidate is gated on a real
convex-polygon overlap fraction (from `footprints.py`). Pairs below the overlap
threshold are dropped and counted, so the reduction is auditable. When overlap
is unavailable (no GSD), the graph falls back to distance-only and is labelled
as a fallback. The degree is capped per frame to keep the matching budget
bounded. The result is the candidate pair graph, with `reduction_factor`
explicitly measured.

### 4. Match features (matching)

For every frame, a downscaled copy is built targeting ~0.6 MP (the brief's
default). A detector (`orb` or `akaze`) finds keypoints and descriptors. Pairs
are matched by k-NN brute-force Hamming distance with Lowe ratio filtering.
Matches below the minimum match count are reported as a status (`insufficient_matches`),
not an exception.

Matching is deferred to a separate step from the transform: the match result
records the matched points; the transform is fit in the next stage. This keeps
the pipeline modular and lets the same match set be used for affine and
homography comparison.

### 5. Align (alignment)

Two transforms are involved. The **pair transform** (`estimate_pair_transform`)
fits one image pair with either a similarity/affine model or a homography model,
RANSAC, ratio-filtered inliers, reprojection RMSE, scale, and rotation. It
fails with a status for too few inliers, degenerate geometry, or excessive
residual.

The **global solve** (`solve_global_alignment`) builds a global *similarity*
(transform with rotation + uniform scale + translation) over the accepted frames
using the pair correspondences and a weak GPS prior. A heading convention
(DJI gimbal yaw normalised) is resolved, and the layout is anchored to the GPS
track.

The **homography comparison** is a separate path: if requested, the pipeline
re-estimates the pair transforms with a homography model and chains placements
through the seed graph. Composition always uses the globally solved similarity
model; homography is recorded as evidence and compared to the similarity solve.
On the Brighton Beach dataset the similarity solve scored better, which is the
expected result for a single-strip, low-parallax dataset.

The output is the per-frame placement (`GlobalPose`) and the output canvas
geometry (`CanvasGeometry`).

### 6. Compose tiles (composition)

The composer works tile by tile. The output canvas is divided into tiles
(default 2048 px). For each tile, the frames whose resolved placement intersects
the tile are selected, downscaled to the tile bounds via `cv2.warpPerspective`,
and blended with feathering and exposure compensation.

Bounded memory is enforced three ways:

- **decode cache** — full-resolution frames are decoded lazily and retained only
  up to `decode_cache_size` (default 2) at a time; the cache is a bounded LRU,
  so the worst case is a small multiple of one frame, not the whole set.
- **sink/stream** — finished RGBA tiles are handed to a sink and dropped; the
  caller streams them into a windowed raster writer. `collect=True` retains them
  (used only by tests on small canvases).
- **tile loop** — the full canvas is never allocated as a single array.

The composer emits progress and "first tile" events so the UI can report
time-to-first-tile.

### 7. Georeference (georeference)

The raster writer (`GeoTiffWriter`) writes a tiled, compressed, 4-band GeoTIFF
with the CRS, transform, and bounds. It writes one windowed block at a time;
the full canvas is never held in memory.

**COG conversion** tries the `rio cogeo` CLI first, then the GDAL COG driver
with a JPEG-compressed RGB + internal mask (textured, small, web-friendly),
falling back to a deflate RGBA COG, and finally reports *unavailable* with the
reason. The COG writer was rewritten to read and write strip by strip so a
large raster does not first allocate the whole thing in memory.

**XYZ tiles** are rendered one window at a time from the GeoTIFF for the chosen
zoom range. The tile budget is capped.

**Preview PNG** is downscaled from the tile tiles into a bounded canvas.

Each output is revalidated on reopen before being reported as produced.

### 8. Export (export)

The final report JSON, metrics CSV, frame table CSV, metadata validation report,
pairs JSON, and the mosaic preview PNG are written to `data/meta/<run_id>/` and
`outputs/<run_id>/`.

## Metrics

Every run builds a `MetricsRecord` in `pipeline.py:_build_metrics` from the
`ResourceSampler` (psutil RSS/CPU/disk) and the stage counters. The sampler
runs on a background thread throughout the run and the peak RSS is the maximum
observed value, not an estimate.

Bandwidth is computed with `transfer_seconds = bytes × 8 / bits_per_second`
using measured byte counts only. Three series are reported:

- **raw imagery** — what a cloud workflow would upload.
- **everything written** — GeoTIFF + COG + tiles.
- **web delivery** — COG + tiles only (what a browser would actually fetch).

When the "everything written" series is larger than the input, the "saved" delta
is reported as negative rather than being hidden. The headline claim is about
*avoiding the raw-imagery cloud transfer*, and that is the accurate series.

## Honesty discipline in the code

- Missing measurements return `null` in the API (a typed `number | null`), never
  `0` or a blank.
- Stages that cannot run are marked `unsupported` with a reason, and the run is
  refused rather than substituting a plausible-looking output.
- Emulated resource limits are labelled as such in the report and in the UI.
- Every product artifact is revalidated on reopen before being reported as
  produced.
- The dataset suitability check is explicit and the rejection reasons are
  surfaced in the report and the UI.
