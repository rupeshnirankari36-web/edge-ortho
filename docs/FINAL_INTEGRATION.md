# Final integration notes

This branch combines `integration/naman-rupesh` and `feat/abhyuday-matching`.

## Canonical runtime

The Naman–Rupesh `edge_ortho.pipeline.run_pipeline` remains the canonical end-to-end
CLI pipeline because it produces the complete evidence set: GeoTIFF/COG, XYZ tiles,
resource samples, metrics, reports, and manifests.

## Integrated feature work

The Abhyuday contribution is retained as reusable modules and an API surface:

- `ingest/reader.py`: EXIF/XMP-style GPS extraction and frame loading.
- `ingest/neighbours.py`: GPS proximity graph helpers.
- `align/matcher.py`: ORB/AKAZE/SIFT matching, ratio filtering, and RANSAC validation.
- `compose/mosaic.py`: bounded mosaic composition helpers.
- `api/main.py`: local FastAPI project/upload/process/results API.

The API adapter invokes the canonical pipeline and maps its `RunSummary` into the API
state and metrics files, so the CLI and API do not maintain competing orchestration
implementations.

## Validation

- 50 tests passed.
- Ruff checks passed for `src` and `tests`.
- All merged source modules compile and import successfully.
