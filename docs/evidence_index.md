# Rupesh Evidence Index

Every row must be completed with actual evidence. Empty, estimated, or unavailable results remain open.

| Requirement | Dataset/run | Git commit | Profile | Command | Timestamp | Artifact | Result/limitation |
|---|---|---|---|---|---|---|---|
| UTM/CRS and affine transform | synthetic fixture |  | laptop | `pytest -q tests/test_geospatial.py` |  | test output | 6 tests currently pass |
| GeoTIFF/COG |  |  |  |  |  | `orthomosaic_cog.tif`, `manifest.json` | Open |
| XYZ tiles |  |  |  |  |  | `tiles/` and byte report | Open |
| QGIS validation |  |  |  |  |  | `qgis_<dataset>.png` | Open |
| Leaflet validation |  |  |  |  |  | `leaflet_<dataset>.png` | Open |
| Mapbox validation |  |  |  |  |  | `mapbox_<dataset>.png` | Open or exact token limitation |
| ODM metadata verification |  |  |  | `exiftool -csv ...` |  | metadata JSON/CSV | Open |
| Esri metadata decision |  |  |  |  |  | verification report | Open |
| 200+ image run |  |  |  |  |  | run report | Open |
| Output handoff to Naman |  |  |  |  |  | run manifest | Open |

## Evidence rule

A green test alone does not prove a real dataset or viewer checkpoint. The artifact must be saved, reproducible, and linked to the commit that produced it. Large images, generated rasters, tiles, model weights, and secrets stay outside Git.
