# Rupesh Strict Traceability Checklist

This file is the acceptance gate for Rupesh’s work. A checkbox is only complete when **implementation, automated/manual test, and evidence** all exist. No hardcoded dataset facts, coordinates, bounds, CRS, tokens, or successful results are allowed.

| ID | Markdown checkpoint | Implementation target | Test/evidence required | Status |
|---|---|---|---|---|
| R-01 | ODM/Esri source links and terms | `data/README.md`, verifier output | Source URL and terms record | Open |
| R-02 | Esri metadata decision | dataset verifier | accepted/rejected report with reason | Open |
| R-03 | UTM/CRS correctness | `geo_export.py` + CRS helpers | synthetic CRS/bounds tests and raster inspection | In progress |
| R-04 | North-up GeoTIFF | writer | raster transform direction test | Open |
| R-05 | RGB + alpha/nodata | writer options | transparent/nodata fixture test | Open |
| R-06 | COG tiling/compression/overviews | COG converter | driver/block/overview validation | Open |
| R-07 | Output metadata manifest | manifest writer | schema and byte-size test | Open |
| R-08 | XYZ tiles | tile generator | tile count, bounds, and pixel fixture test | Open |
| R-09 | QGIS validation | `docs/viewer_validation.md` | QGIS/GDAL inspection record and screenshot | Open |
| R-10 | Leaflet viewer | `viewer/leaflet/index.html` | local server smoke test and screenshot | Open |
| R-11 | Mapbox viewer | `viewer/mapbox/index.html` | token-free config test and screenshot/limitation | Open |
| R-12 | Abhyuday stable inputs | JSON contract loader | fixture validation and no private imports | Open |
| R-13 | First-tile event | composer/export callback | callback test and metrics handoff | Open |
| R-14 | Naman output handoff | run manifest | COG/tile paths, bytes, CRS, bounds, GSD | Open |
| R-15 | Evidence index | `docs/evidence/evidence_index.md` | every artifact has dataset, commit, command, profile, date, requirement | Open |
| R-16 | Smoke dataset | run command | real ODM run record | Open |
| R-17 | 200+ image run | run record only; datasets ignored | stress evidence and limitations | Open |
| R-18 | Flat-ground limitation | final report | explicit non-survey-grade statement | Open |
| R-19 | No secrets/large data | `.gitignore`, CI check | repository scan | Open |
| R-20 | PR review | GitHub PR | Abhyuday and Naman review requested | Open |

## No-hardcoding rules

- Dataset facts must come from downloaded metadata, never from a constant in source code.
- CRS must be derived from validated coordinates or an explicit input argument.
- Raster bounds, dimensions, GSD, and byte sizes must be read from the actual run.
- Viewer bounds must be loaded from the run manifest.
- Mapbox tokens must come from runtime configuration only.
- “Accepted”, “successful”, “200+ images”, and performance values require saved evidence.
- If a tool or dataset is unavailable, record the exact limitation; do not fabricate a pass.

## Gate order

1. Contracts and validation.
2. GeoTIFF/COG export.
3. XYZ tiles and manifest.
4. QGIS/Leaflet/Mapbox validation.
5. Dataset verification and real runs.
6. Evidence index and PR review.
