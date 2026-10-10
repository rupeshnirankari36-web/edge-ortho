# EdgeOrtho — implemented vs measured vs approximations vs future

This is the companion to the README and the demo script. It is the explicit
disclaimer list the brief asks for: implemented features, measured results,
approximations, and future work, clearly separated.

## Implemented (real, tested, working)

- Full eight-stage pipeline: ingest → validate GPS → plan neighbours → match
  features → align → compose tiles → georeference → export.
- Metadata reader: EXIF GPS/altitude/focal length/camera model, DJI XMP relative
  and absolute altitude, gimbal yaw/pitch, XMP GPS.
- Frame validation: missing GPS, null-island GPS, out-of-range GPS, zero-size
  files, unreadable files, unsupported formats, all rejected with a reason.
- Dataset suitability: minimum 4 accepted frames; dataset warnings including
  absolute-altitude-only flag; suitability report surfaced in the API and UI.
- Planner: KD-tree on projected centres, adaptive candidate radius from measured
  footprint, convex-polygon overlap gating, link cap, overlap fallback label.
- Matching: downscaled copies (~0.6 MP default), ORB or AKAZE, k-NN brute-force
  with Lowe ratio filtering, status codes for bad pairs, no exceptions for
  unreadable frames.
- Pair transform: affine/similarity (RANSAC) and homography (RANSAC), with
  inliers, reprojection RMSE, scale, rotation, and failure statuses.
- Alignment: global similarity solve with weak GPS prior, heading convention
  resolution, GPS-track anchor, homography comparison recorded when requested.
- Composer: tile-by-tile stream, bounded decode cache, exposure compensation,
  feathered blending, first-tile event, no full-canvas allocation.
- Raster writer: tiled GeoTIFF with CRS/transform/bounds, GDAL block-cache cap,
  reopen validation.
- COG conversion: `rio cogeo` CLI first, then GDAL COG driver with JPEG
  RGB + internal mask, then deflate RGBA fallback, then unavailable report.
- XYZ tiles: one-window-at-a-time rendering with zoom budget cap.
- Preview PNG: downscaled composited raster preview.
- API: system, sources (inspect and upload), runs (create/list/get/pairs/delete
  with SSE), artifact routes (preview, GeoTIFF, COG, tiles, tiles zip, frame
  source, report JSON, metrics CSV, frames CSV, metadata report JSON), performance
  (records, export JSON/CSV), and settings.
- Frontend: overview, new project, processing workplace, map viewer, results
  and export, performance lab, history, settings.
- SQLite run store with run records, stage counters, pairs, performance records,
  settings persistence, and artifact lists.
- Performance ledger with per-run records, bandwidth scenarios at 1/5/20 Mbps,
  affine-vs-homography comparison where available, RAM-vs-frame chart from real
  runs, profile list, and exportable JSON/CSV.
- Measured values only: wall clock, peak RSS, baseline RSS, peak delta, CPU
  (per-core and machine), disk deltas, throughput, bandwidth, reduction factors.
  Unmeasured values return `null` and render as "not measured".

## Measured on this machine (Brighton Beach, 18 frames, BSD 2-Clause, Piero Toffanin)

These are from stored run reports in `data/meta/<run_id>/` after three runs.

- **Dataset:** 18 accepted geotagged DJI FC300S frames, ~84 m extent, ~0.018 m/px
  estimated GSD, UTM zone 15N (EPSG:32615).
- **Default (laptop, affine):**
  - wall clock 144.6 s, peak RSS 1067 MB, baseline 130 MB, delta 937 MB,
  - first tile 1.85 s, throughput 0.12 fps,
  - 67 of 91 pairs aligned, 24 failed, 6213 ratio-filtered matches, 6213 inliers,
  - mean reprojection error 0.41 px, mean GPS placement error 1.66 m,
  - residual RMSE 0.27 m, alignment: 67 constraints, 1511 correspondences.
  - Output 7743×7748 px, 4 bands, EPSG:32615, 0.022389 m/px, 4-band RGBA.
  - GeoTIFF 149.6 MB, COG 9.8 MB (GDAL COG driver, JPEG mask, internal mask,
    overviews 2/4/8/16), 24 XYZ tiles at z16–z19.
  - Production products larger than input: "everything written" 168.1 MB vs
    64.9 MB input.
- **pi-class (4 cores, 4 GB soft ceiling, affine + homography):**
  - wall clock 134.8 s, peak RSS 1074 MB, baseline 277 MB, delta 797 MB,
  - CPU affinity applied to cores 0–3, 4 GB RAM ceiling enforced as a soft abort.
  - First tile 1.47 s, throughput 0.13 fps.
  - Same frames/pairs/inliers/reprojection as above.
  - Homography comparison available: 31 of 91 pairs re-estimated with homography,
    60 rejected; similarity mean GPS error 1.66 m, homography chain mean GPS error
    3.08 m, placement disagreement 2.35 m.
  - COG and tiles identical in size except the run_id.
- **pi-class with streaming COG rewrite (standalone COG conversion, same raster):**
  - peak RSS 389 MB vs 665 MB before the rewrite; baseline ~52 MB; rise 337 MB vs
    613 MB. This is from one standalone conversion on one raster, not a full pipeline
    run.

### Bandwidth (from the pi-class affine+hg run)

- input bytes (raw imagery): 64.9 MB
- COG + tiles (web deliverable): 19.5 MB (COG 9.8 MB + tiles 9.7 MB)
- lossless GeoTIFF: 149.6 MB
- everything written: 168.1 MB
- formula: `transfer_seconds = bytes × 8 / bits_per_second`
- at 1 Mbps: input ~8.7 min, web ~2.6 min, everything ~22.4 min
- web reduction factor: 3.32× (raw/web)
- product reduction factor: 0.39× (raw/everything written) — negative saving figure
  for the "everything written" series, reported as negative in the bandwidth panel
  rather than hidden.

### RAM-vs-image-count chart data (real recorded runs)

- 18 frames, peak RSS 1067 MB (laptop, affine)
- 18 frames, peak RSS 1074 MB (pi-class, both)

## Approximations (deliberate, documented in the UI)

- **Exposure compensation:** per-frame median-brightness match over a 128-px
  downscaled sample; clipped to 0.8–1.25; deliberately approximate.
- **Neighbour radius:** adaptive to measured footprint diagonal, not a fixed
  magic number.
- **Overlap estimation:** real convex-polygon overlap when geometry is known;
  otherwise distance-only with a fallback label and no overlap figure.
- **Heading fallback:** GPS-track bearing when no camera-yaw tag exists; a
  modelling approximation, not a measured heading.
- **GSD:** from metadata when altitude, focal length, and sensor/35mm-equiv are
  available; reported with its source. When only absolute altitude exists, the
  altitude is flagged as approximate.
- **Homography comparison:** computed and recorded as evidence; composition always
  uses the similarity solve.
- **Memory sampling:** RSS sampled on a background thread at 0.1 s; peak RSS is
  the maximum observed, not inferred. psutil disk counters are differenced across
  the run and may be unavailable on some hosts (reported with the reason).
- **COG-stream memory improvement:** one offline measurement on one raster; evidence
  the path is better bounded, not a general claim.

## Not yet implemented / future work

- **Ground control.** No GCPs or check points; no absolute accuracy measurement.
  The numbers are internal-consistency evidence.
- **Bundle adjustment beyond the current constrained global solve.**
- **Relief elevation / true orthorectification.** The current composer assumes
  near-nadir, planar RGB; it does not model height or parallax.
- **Physical-device evaluation** on a real pi-lite, pi-class, or jetson-class
  device. The pi-class run is on the host with an emulated constraint; it is not
  evidence of performance on that hardware.
- **Broader dataset evaluation** beyond the 18-frame Brighton Beach sample.
- **3D reconstruction, DEM, multi-spectral, oblique imagery handling.**
- **Live map refresh while composing** — the map viewer currently shows output that
  exists at load time.
- **Frontend performance-lab charts beyond the RAM-vs-frame line and the
  bandwidth table** (the chart is currently hand-rolled SVG from real run records).

## What "measured but not general" means in this context

The measured numbers are from specific runs on one machine. They are real and
reproducible on a machine with the same dependencies, but they are not general
performance or accuracy claims. The briefing doc says this explicitly: these are
what was measured on this machine, not what any user can expect from any machine
or any dataset.

## How to validate a fresh copy

1. Install the dependencies (Python backend, Node frontend).
2. Start the backend.
3. Run `scripts/e2e_check.py` or the demo script against a sample dataset.
4. Confirm the report shows `status=succeeded`, the GeoTIFF reopens with a CRS,
   the COG reopens with overviews and a mask, and the performance records show
   real wall-clock and RSS values.
5. Pair the frontend with `npm run dev` or the built-UI path and use the
   Brighton Beach sample to walk the full UI flow.

## How to read this list against the brief

- The brief asks for privacy by default, measurable performance, reduced image
  comparisons, bounded memory, and honest results. The implementation meets those
  in the form of a real vertical slice on real imagery, with real measurements.
- The brief also asks for a clear separation of implemented features, measured
  results, approximations, and future work. This file is that separation.
