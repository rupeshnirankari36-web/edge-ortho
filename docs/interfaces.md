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

## Phase 2 output manifest

`manifest.json` records the actual raster and tile outputs, including CRS, projected bounds, WGS84 bounds, dimensions, pixel size/GSD, COG bytes, tile directory, zoom range, tile count, and tile bytes.

Any schema change requires an issue and pull-request review from the affected members.
