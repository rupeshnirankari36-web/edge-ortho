# Shared Interfaces

These are the public file and event contracts for integration. Rupesh consumes serializable files only and does not import Abhyuday’s private CV classes.

## `poses.json`

```json
{
  "poses": [
    {
      "frame_id": "string",
      "x": 0.0,
      "y": 0.0,
      "scale": 1.0,
      "rotation": 0.0,
      "confidence": 0.0,
      "dropped": false
    }
  ]
}
```

`x` and `y` must be in the projected CRS declared by `canvas.json`. `frame_id` is the stable identifier used by Abhyuday’s frame records.

## `pair_transforms.json`

```json
{
  "pairs": [
    {
      "source_id": "string",
      "target_id": "string",
      "model": "affine|homography|similarity",
      "matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
      "matches": 0,
      "inliers": 0,
      "reprojection_error": 0.0,
      "status": "accepted|rejected|fallback"
    }
  ]
}
```

Rupesh does not reinterpret matching thresholds. This file is optional for export-only tests but required for a full end-to-end run.

## `canvas.json`

```json
{
  "crs": "EPSG:32643",
  "left": 0.0,
  "top": 0.0,
  "pixel_size": 0.1,
  "width": 2048,
  "height": 2048,
  "gsd": 0.1,
  "source_dataset": "dataset-derived-name"
}
```

The CRS, bounds, dimensions, GSD, and dataset name must come from the actual run. They must not be hardcoded in viewer or export code.

## Phase 2 events

The compositor calls the optional callback with JSON-compatible events:

```json
{"event":"first_tile","row":0,"col":0,"width":2048,"height":2048}
{"event":"tile_written","row":0,"col":2048,"width":2048,"height":2048}
{"event":"final_output","path":"outputs/run/orthomosaic.tif","bytes":12345}
```

Naman can record time-to-first-tile from `first_tile` and final output accounting from `final_output` without accessing private objects.

## Abhyuday CV Integration Hand-off (Ingestion, Matching, Alignment, Blending)

### Generated Output Contracts
When `compose_mosaic(...)` or `run_pipeline(...)` runs, the following standard JSON contracts are generated in `output/`:
- `poses.json`: Projected coordinates, scale, rotation angle, and confidence for every frame. Frames placed visually have `confidence: 1.0`; frames placed via GPS prior fallback have `confidence: 0.5`.
- `pair_transforms.json`: Complete record for each candidate pair, including `model` (`affine`, `homography`, or `similarity`), 3x3 transformation matrix, candidate matches, RANSAC inliers, inlier ratio, and RMS reprojection error.
- `canvas.json`: CRS (`EPSG:4326` or UTM), left/top origin, pixel size/GSD, dimensions, and source dataset name.

### Nodata and Alpha Semantics
- **Nodata Value**: `0` for raw black border pixels.
- **Blending / Alpha Mask**: Smooth feathering is applied using Euclidean distance transform with configurable radius (default: 25px).
- **Exposure Compensation**: Gentle frame luminance gain clamped between [0.8, 1.25] balances brightness across frames without blowing out highlights.
- **Warp Execution**: Images are downscaled safely to ~0.6 MP for feature detection, and warped on-demand per frame/tile during composition, guaranteeing that full-resolution uncompressed images are never retained simultaneously in memory.

### Known-Good Command
To execute the pipeline end-to-end with specific matcher and transform modes:
```bash
python -m edge_ortho.pipeline
# Or via Python API:
from edge_ortho.pipeline import run_pipeline
run_pipeline(
    project_dir="data/projects/demo",
    raw_dir="data/raw/demo",
    matcher="orb",              # Options: "orb", "akaze", "sift"
    transform_model="affine",   # Options: "affine", "homography", "similarity"
    match_pixels=600_000,
    debug_matches=True,
)
```

