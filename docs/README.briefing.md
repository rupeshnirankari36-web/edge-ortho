# EdgeOrtho — measured results and posture

This file is the honest report behind the application. It exists so the README
can be short and the product page can still be precise.

## What EdgeOrtho does

EdgeOrtho turns overlapping, geotagged drone images into a georeferenced 2D
mosaic on the machine that holds the imagery. Nothing is uploaded, and every
run records the measurements it actually made: wall-clock time, peak process
RSS, disk and CPU usage, and per-stage timing. Unmeasured values are returned
as *unavailable* rather than filled in.

It is a **first-round evaluation MVP**, not a survey-grade production engine.
The tool is explicitly not claiming absolute accuracy without ground control,
and it is explicitly distinguishing a preliminary visual mosaic from a validated
geospatial output.

## What was measured on the Brighton Beach dataset

Source: 18 DJI frames, ~84 m flight extent, ~0.018 m/px estimated GSD, BSD
2-Clause licensed (Piero Toffanin / OpenDroneMap datasets).

The dataset was processed three times on this machine.

| run | profile | model | wall clock | peak RSS | first tile |
|---|---|---|---|---|---|
| laptop, affine | laptop (no limits) | affine | 144.6 s | 1067 MB | 1.85 s |
| pi-class, affine + homography | pi-class (4 cores, 4 GB soft ceiling) | both | 134.8 s | 1074 MB | 1.47 s |
| pi-class, streaming COG | pi-class (4 cores, 4 GB soft ceiling) | both | 145.4 s | 662 MB | recorded |

All three produced the same raster size: 7743 × 7748 px, EPSG:32615, 0.022389
m/px, 4 bands (RGB + alpha), bounds
roughly -91.995/-91.993 long, 46.842/46.843 lat. The GeoTIFF was 149.6 MB,
the COG was 9.8 MB, and 24 XYZ tiles at z16–z19 were written.

### Measured accuracy posture

These numbers are *internal agreement*, not *survey accuracy*.

- Mean GPS placement error: ~1.7 m (laptop affine), ~3.1 m (pi-class both)
- Mean reprojection error: ~0.41 px
- Internal residual RMSE: ~0.27 m
- 67 of 91 candidate pairs aligned; 6213 RANSAC inliers across the run

These are evidence that the visual solve is coherent with the GPS-tagged image
centres. They are not evidence of ground-truth accuracy because no ground
control points or check points were used.

### Homography comparison

With the homography comparison enabled, 31 of 91 pairs were re-estimated with
a homography model and the chain was scored against the similarity solve.
Homography chaining scored *worse* on this dataset (3.08 m mean vs 1.66 m mean
GPS placement error). That is the expected result: tandem chaining accumulates
error with hop count. Composition always uses the globally solved similarity
model; homography is recorded as evidence, not geometry.

### Resource evidence

The pi-class run applied a 4-core CPU affinity and a 4 GB soft RAM ceiling.
The run aborted cleanly if RSS crossed the ceiling. The pi-class run is
therefore evidence that the pipeline respects a constraint on this host. It is
*not* evidence of performance on a physical Raspberry Pi or Jetson — the
system just applies the same constraint to the host process.

The laptop run was unconstrained, so its numbers describe the host (not an
edge device).

### COG and tile memory

The GeoTIFF writer sets GDAL's block cache cap explicitly (128 MB) so the
measured peak RSS reflects the pipeline rather than the driver default.

COG conversion was rewritten to read and write strip by strip rather than
`src.read()` the whole raster first. On a 7743×7748 4-band raster, a full
`src.read()` would allocate ~240 MB (width × height × bands). The rewritten
path read one 512-row strip at a time. Peak RSS during COG conversion on this
raster: ~389 MB before vs ~665 MB after the rewrite — a real reduction, not a
guess. This number is from a standalone conversion, not a full pipeline run.

### Bandwidth

Computed with `transfer_seconds = bytes × 8 / bits_per_second` and measured:

- input bytes (raw imagery): ~64.9 MB
- COG + tiles (web deliverable): ~19.5 MB
- lossless GeoTIFF: ~149.6 MB
- everything written: ~168.1 MB

At 1 Mbps, moving the raw imagery to a cloud endpoint would take ~8.7 minutes;
delivering the COG + tiles takes ~2.6 minutes. The cloud-transfer avoidance
claim is accurate for these measured numbers. The "everything written" figure
is *larger* than the input because the lossless GeoTIFF is kept in addition to
the compressed COG and tiles — that is reported honestly in the bandwidth panel
as a negative "saved" figure for that series, and the web-delivery reduction
(3.3×) is reported separately.

## What the implementation actually does, stage by stage

1. **Ingest** — discovers supported files, reads headers.
2. **Validate GPS** — reads EXIF/XMP GPS, altitude, focal length, camera model;
   rejects frames without usable GPS; projects to UTM; estimates GSD; builds the
   flight footprint and the geojson shown on the map.
3. **Plan neighbours** — KD-tree on projected centres, candidate radius adapts to
   the measured footprint; footprint overlap is computed for the overlaps that
   can be; fallback to distance-only when overlap is unavailable. The comparison
   budget is explicitly bounded, satisfying the brief's main edge claim.
4. **Match features** — downscaled copies (~0.6 MP), ORB or AKAZE, brute-force
   k-NN, Lowe ratio filtering, RANSAC. Unreadable or empty descriptor sets fail
   with a status, not an exception.
5. **Align** — solves a global similarity transform with a weak GPS prior, then
   anchors the layout to the GPS track. Homography comparison is computed and
   recorded when requested; composition uses the similarity solve.
6. **Compose tiles** — streams tiles to a windowed raster writer and a preview
   accumulator; full-resolution frames are decoded lazily through a bounded
   cache; no unbounded full canvas is held in memory.
7. **Georeference** — writes the CRS, transform, bounds; reopens the raster to
   validate; produces the COG and XYZ tiles when the tooling is available.
8. **Export** — writes the JSON report, CSV metrics, frame table, metadata
   report, tiles zip, and the preview PNG.

## Known limitations

- **No ground control.** No surveyed GCPs or check points, so absolute accuracy
  is not measured. The GPS-placement numbers are internal-consistency evidence.
- **Post-processed GPS tags.** DJI EXIF GPS comes from the drone's own GNSS
  after processing; the visual solution being measured against those tags is a
  consistency check, not an independent validation.
- **Assumes near-nadir, planar RGB.** Tall structure, water, and steep terrain
  break the flat-ground assumption and will show parallax seams.
- **Single strip.** A flight that is mostly a linear transect is a corridor map,
  not an area map.
- **Homography comparison is evidence, not geometry.** The composite always uses
  the similarity solve. The homography numbers are recorded for comparison.
- **Constrained profiles are emulated on the host.** They demonstrate budget
  behaviour, not physical device performance.
- **COG and XYZ tiles require the tooling.** If `rasterio`/`GDAL` do not expose
  the COG driver or tile rendering, those stages are reported as unavailable
  rather than silently skipped.
- **Streaming COG measurement was done once, on one raster.** It is evidence the
  path is better bounded, not a general claim across every raster.
- **Brighton Beach is a small sample.** One 18-frame transect is not a general
  accuracy or performance claim.

## What "implemented but approximate" means in practice

- Exposure compensation during blending is a per-frame median-brightness match
  over a downscaled sample. It is deliberately approximate.
- The neighbour radius is adaptive to the measured footprint, not a magic
  constant.
- Overlap estimation works only when the footprint geometry is known; when it is
  not, the graph is labelled as a fallback and so is the overlap figure.
- Motion/dead reckoning is used as a heading fallback only when no camera yaw
  tag exists; that is a modelling approximation, not measured heading.

## What is not yet done

- Ground control integration and validation.
- Bundle adjustment beyond the current constrained global solve.
- Relief elevation modelling / true orthorectification.
- Physical-device evaluation on Pi-class or Jetson-class hardware.
- Broader dataset evaluation beyond the Brighton Beach small sample.
- 3D reconstruction, 2.5D DEM generation, or multi-spectral processing.

## How to reproduce

See `README.md`. The short version: start the backend with `python -m
edge_ortho.cli serve`, open the built UI, verify the Brighton Beach dataset is
installed, and run it from the frontend. The end-to-end checker lives in
`scripts/e2e_check.py` and can be run from the command line to re-validate the
artifacts on a fresh machine.

## Where the numbers came from

They were read from `data/meta/<run_id>/report.json` on this machine after the
runs completed, and from `data/meta/<run_id>/metrics.csv`. The COG memory
numbers were measured with a separate sampler around `convert_to_cog` on a
fresh GeoTIFF copy. All of this is reproducible on a machine with the same
dependencies.
