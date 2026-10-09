# Phase 2 Validation Record

## Scope

Phase 2 covers stable JSON contracts, windowed GeoTIFF composition, COG conversion, XYZ tiles, first-tile/final-output events, and the output manifest. Viewer implementation and dataset screenshots remain Phase 3.

## Automated validation

Command:

```bash
PYTHONPATH=src python3 -m pytest -q
```

Result at implementation checkpoint:

```text
10 passed, 2 non-blocking PendingDeprecationWarning messages
```

Phase 2-specific command:

```bash
PYTHONPATH=src python3 -m pytest -q tests/test_phase2.py
```

Result:

```text
3 passed
```

## Covered behaviors

- `poses.json` and `canvas.json` are loaded from public JSON contracts.
- Missing required contract fields fail with an explicit error.
- Composition writes one raster window at a time.
- Renderer output shape and dtype are validated.
- `first_tile`, `tile_written`, and `final_output` events are emitted.
- GeoTIFF CRS, dimensions, transform, and raster data are checked.
- XYZ tile bounds are calculated from runtime raster bounds and requested zoom.
- PNG tile count and byte size are measured from generated files.
- COG bytes and output metadata are read from actual files.
- Manifest includes output paths, CRS, projected/WGS84 bounds, pixel size, COG bytes, and tile report.

## Open real-run checks

These are intentionally not marked passed until a real Abhyuday output and accepted dataset are available:

- Full frame composition from actual `poses.json`, `pair_transforms.json`, and `canvas.json`.
- `gdalinfo`/`rio info` logs saved under a real output run.
- Tile count and bytes from an actual ODM dataset.
- 200+ image edge run and resource evidence.
- QGIS/Leaflet/Mapbox validation, which belongs to Phase 3.

No real dataset, generated raster, tile directory, or secret is committed to Git.
