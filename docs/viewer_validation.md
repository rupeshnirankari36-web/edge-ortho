# Viewer and GIS Validation

## QGIS

1. Open the final `orthomosaic_cog.tif` in QGIS.
2. Confirm the layer CRS matches `manifest.json`.
3. Confirm bounds, pixel size, north-up orientation, and transparent nodata.
4. Add a known basemap when available and record whether the mosaic lands in the expected area.
5. Capture a screenshot showing the layer name, map position, and visible imagery.
6. Record the exact Git commit, dataset, profile, command, and timestamp in the evidence index.

CLI validation where available:

```bash
gdalinfo outputs/<run>/orthomosaic_cog.tif
rio info outputs/<run>/orthomosaic_cog.tif
```

If QGIS/GDAL is unavailable, record that exact limitation and retain rasterio validation output. Do not mark the QGIS checkpoint passed without visual evidence.

## Leaflet

```bash
python -m http.server 8000 --directory viewer/leaflet
```

Open `http://localhost:8000/?manifest=<relative-run-manifest>&tiles=<relative-tile-template>`. The viewer must derive bounds and labels from the manifest.

## Mapbox GL JS

Do not commit a token. Supply it only at runtime, for example through a local `window.MAPBOX_TOKEN` configuration or an environment-driven wrapper. If no token is available, verify the static implementation and record the exact limitation; do not claim a successful Mapbox render.

## Required viewer checks

- [ ] The COG and both web viewers use the same run manifest.
- [ ] Leaflet and Mapbox bounds are runtime-derived.
- [ ] Tile URL and zoom range are runtime-derived.
- [ ] Attribution is present.
- [ ] No token is committed.
- [ ] QGIS screenshot exists and is indexed.
- [ ] Leaflet screenshot exists and is indexed.
- [ ] Mapbox screenshot exists or limitation is indexed.
