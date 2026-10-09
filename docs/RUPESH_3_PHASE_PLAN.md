# Rupesh Work — Three-Phase Execution Plan

**Branch:** `feat/rupesh-cog-viewers`
**Owner:** Rupesh
**Integration partners:** Abhyuday (poses/composition inputs), Naman (metrics/output accounting)

## Goal
Turn the aligned frame/pose outputs into a geographically valid orthomosaic, a validated GeoTIFF/COG, XYZ raster tiles, three viewers, and a reproducible evidence pack.

> Scope boundary: this project is a flat-ground, mostly nadir 2D mosaic pipeline. It is not survey-grade terrain-aware orthorectification or full 3D photogrammetry.

## Phase 1 — Geospatial foundation and contracts
**Outcome:** A tested geospatial core that can validate frame locations, select a UTM CRS, compute raster bounds, and define the stable hand-off contract.

### Checklist
- [x] Create the dedicated Rupesh branch.
- [x] Add the three-phase plan and acceptance checklist.
- [x] Define serializable frame, pose, canvas, and output manifest contracts.
- [x] Implement longitude/latitude validation and UTM EPSG selection.
- [x] Implement north-up canvas bounds and affine pixel/world conversion helpers.
- [x] Add unit tests for valid/invalid coordinates, UTM zones, bounds, and round trips.
- [ ] Integrate Abhyuday `poses.json`, `pair_transforms.json`, and `canvas.json` fixtures.
- [ ] Verify one real ODM sample after dataset download.

### Phase 1 evidence
- `pytest -q tests/test_geospatial.py`
- Contract examples under `tests/fixtures/`
- A validation report containing CRS, bounds, GSD, and frame counts.

## Phase 2 — GeoTIFF/COG export and tile generation
**Outcome:** One north-up georeferenced raster plus validated cloud-optimized output and XYZ tiles.

### Checklist
- [ ] Consume stable pose/canvas files without importing private CV classes.
- [ ] Implement tile-by-tile composition with bounded memory.
- [ ] Write RGB plus alpha/nodata GeoTIFF with the correct CRS and affine transform.
- [ ] Convert to COG with internal tiling, compression, and overviews.
- [ ] Generate XYZ tiles from the final georeferenced output.
- [ ] Emit first-tile and final-output events for Naman’s metrics collector.
- [ ] Validate with `gdalinfo` and/or `rio info`.
- [ ] Record raster dimensions, pixel size, bounds, CRS, and byte sizes.

### Phase 2 evidence
- `outputs/<run>/orthomosaic_cog.tif`
- `outputs/<run>/tiles/`
- `outputs/<run>/manifest.json`
- GDAL/rasterio validation logs
- Tile count and byte-size report

## Phase 3 — Viewers, datasets, and final evidence
**Outcome:** The result is demonstrable in QGIS, Leaflet, and Mapbox, with reproducible dataset and performance evidence.

### Checklist
- [ ] Verify ODM and Esri source metadata and terms.
- [ ] Record accepted/rejected datasets and exact reasons.
- [ ] Add QGIS validation instructions and screenshot.
- [ ] Implement Leaflet raster-tile viewer with bounds and attribution.
- [ ] Implement Mapbox GL JS raster viewer with token-free local configuration.
- [ ] Add evidence index linking each artifact to a requirement and Git commit.
- [ ] Add affine-vs-homography, RAM-scaling, bandwidth, metrics, and ODM comparison evidence.
- [ ] Run the smoke dataset end-to-end.
- [ ] Run or document the 200+ image stress run.
- [ ] Open the Rupesh PR only after all checks pass.

## Integration contract
Rupesh consumes these public files:

```text
poses.json
pair_transforms.json
canvas.json
```

The final run directory must expose:

```text
orthomosaic.tif
orthomosaic_cog.tif
tiles/
manifest.json
metrics.json
report.md
```

Every phase must leave implementation, tests, and evidence together. No datasets, generated rasters, tiles, tokens, or model weights may be committed.
