# Naman + Rupesh Integration Branch

**Branch:** `integration/naman-rupesh`

## Canonical ownership

- **Abhyuday:** alignment and serialized `poses.json`, `pair_transforms.json`, and `canvas.json` inputs.
- **Rupesh:** public Phase 2 contracts, windowed geospatial export, COG/XYZ output, and runtime-derived manifest.
- **Naman:** resource monitoring, first-tile timing, bandwidth calculations, CSV/JSON/Markdown reports, and resource chart.

## Integration boundary

Rupesh’s Phase 2 compositor emits JSON-compatible events. Naman’s `Phase2MetricsBridge` consumes those events without importing private CV or raster classes.

Required event sequence:

```text
first_tile -> tile_written* -> final_output
```

The bridge writes:

```text
metrics.json
metrics.csv
report.md
resources.png
```

## Required run outputs

```text
orthomosaic.tif
orthomosaic_cog.tif
tiles/
manifest.json
metrics.json
metrics.csv
report.md
resources.png
```

`report.json` remains as a backward-compatible alias for Naman’s existing CLI/report consumers.

## Gate before merging to `main`

```bash
python3 -m pytest -q
ruff check src tests
```

The synthetic combined gate currently passes 19 tests. Real ODM input, real Abhyuday pose files, `rio info`/`gdalinfo` evidence, and 200+ image stress evidence remain required before the final pull request.
