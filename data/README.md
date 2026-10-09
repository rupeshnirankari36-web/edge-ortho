# Datasets & Ingestion Log

This directory manages dataset documentation, metadata verification records, and local data guidelines for `edge-ortho`.

> **Note:** Raw image folders (`data/raw/`) and outputs (`outputs/`) are ignored by Git. Never commit raw aerial imagery to this repository.

---

## 1. Supported Reference Datasets

### OpenDroneMap (ODM) Reference Datasets
- **`brighton_beach`** (18 images) - Fast smoke test / local verification.
- **`mygla`** (29 images) - Metadata parsing and baseline orthomosaic generation.
- **`aukerman`** (77 images) - Primary stable demonstration dataset (agricultural / planar).
- **`toledo`** (87 images) - Secondary evaluation dataset.
- **`sheffield_park_1`** (78 images) - Flat urban park for fair ODM planar comparisons.
- **`sheffield_cross`** (172 images) - Ground Control Point (GCP) accuracy evaluation.
- **`wietrznia`** (225 images) - High-frame-count stress dataset (200+ images).
- **`waterbury`** (248 images) - RTK-enabled high-frame-count stress dataset.

### Esri Sample Drone Datasets
- **Esri Campus / Redlands Building E Construction**
- **Superior Marshall Wildfire**
- **Redlands Packing House District**

---

## 2. Dataset Acceptance & Verification Command

Before ingestion into the pipeline, all datasets must be audited with ExifTool:

```bash
exiftool -csv \
  -GPSLatitude -GPSLongitude -GPSAltitude -RelativeAltitude \
  -FlightYawDegree -GimbalPitchDegree -FocalLength \
  -ImageWidth -ImageHeight -Model -DateTimeOriginal \
  data/raw/<dataset>/images > data/meta/<dataset>.csv
```

### Acceptance Criteria
- Every usable frame must contain valid Latitude and Longitude.
- Camera orientation must be mostly nadir (Gimbal pitch $\approx -90^\circ$).
- Camera sensor model and focal length must be consistent across the run.
- Spatial GPS distribution must conform to a lawnmower/grid flight pattern.
- Frames must be standard 3-channel RGB (JPEG or TIFF).

---

## 3. Dataset Audit Log

| Dataset Name | Source | Total Frames | Accepted Frames | Status | Rejection / Validation Reason |
|---|---|---|---|---|---|
| `sample_synthetic` | Built-in generator | 12 | 12 | Accepted | Synthetic test flight grid with known UTM coordinates and EXIF |
| `brighton_beach` | ODM | 18 | 18 | Accepted | Verified GPS, nadir pitch, suitable for smoke tests |
| `aukerman` | ODM | 77 | 77 | Accepted | Full EXIF coverage, flat farmland, benchmark reference |
| `wietrznia` | ODM | 225 | 225 | Accepted | Verified for 200+ stress testing |
