# Datasets and the license audit

EdgeOrtho distributes **no imagery**. The code produces nothing from scratch —
it processes imagery the user supplies. For evaluation, it ships a small public
sample-acquisition path that downloads a public dataset and records the licence
and source so the audit is reproducible rather than implied.

## Sample dataset

The first-run sample follows the brief's public-dataset guidance. It is the
**Brighton Beach** dataset:

- **Source:** `https://github.com/pierotofy/drone_dataset_brighton_beach`
- **Vendor reference in brief:** OpenDroneMap example datasets
  (`https://www.opendronemap.org/odm/datasets/`)
- **License:** BSD 2-Clause (Copyright (c) 2017, Piero Toffanin)
- **Credit:** Piero Toffanin / OpenDroneMap datasets
- **License file:** `data/raw/brighton_beach/DATASET_MANIFEST.json`
- **Content:** 18 DJI FC300S frames with EXIF GPS, DJI XMP relative altitude
  and gimbal angles, one overview JPEG, and a `dsm.tif`.
- **Use in this project:** evaluation only. Downloaded on first run; not
  redistributed with the repo. The raw imagery lives in `data/raw/`, which is
  git-ignored.

This dataset is deliberately small and fast so the first vertical slice is
realistic: 18 frames, ~84 m extent, ~0.018 m/px estimated GSD, one linear
transect with real overlap.

## Why this dataset, not a larger one

The brief asks for a realistic first-round MVP with a small sample. A larger
dataset would enlarge the first-run download and the first-run processing time
without improving what the MVP demonstrates: ingest, GPS validation, neighbour
planning, matching, alignment, composition, georeference, export, and measured
performance.

## Dataset suitability in the product

Before processing, the dataset is inspected and a suitability report is produced:

- Frames without GPS are rejected as `missing_gps`.
- Frames with null-island coordinates are rejected as `invalid_gps`.
- Frames whose altitude or focal length cannot be read cannot support a metric
  GSD estimate, and the report states that.
- The dataset approval requires at least 4 accepted geotagged frames — this is
  the minimum to attempt a mosaic, and the report says so.
- Absolute altitude without a relative reading is flagged as approximate.

These are all surfaced in the frontend as dataset warnings.

## Other public options if you want a larger test

You can point the backend at any folder of geotagged JPG/JPEG/TIFF imagery
that carries EXIF or XMP GPS. The sample path is only a convenience for first
use. If you have your own DJI 원본 or similar, copy or symlink it into
`data/raw/<your-name>/` and inspect that path.

Before using a dataset you do not own, check its license the same way this
project does: record the source, the license, and the credit, and do not
redistribute the imagery with the project.

## What the license audit requires

The brief requires a "license audit before a dataset is accepted". For the
sample this was done at acquisition time: the licence is written into the
manifest, the source is recorded, and the credit is recorded. For any other
dataset you supply, the same discipline applies: keep the licence and credit
with the dataset, and do not assume a public-sounding license is compatible just
because the imagery appears online.

## Why no cloud samples

The brief's privacy and bandwidth story is that raw imagery stays local. Fetching
a dataset over the internet for *local* processing is the acceptable path for
first use, not a violation: once downloaded, the frames are processed and stored
locally. The fetch path is explicitly in the source list so this is traceable.

## Dataset folder layout expected by the product

Either:

- a folder containing only supported image files, or
- a folder containing the images plus other files (the product skips unsupported
  ones and reports them), or
- a single supported image file.

For the sample dataset the layout is:

```
data/raw/brighton_beach/
  DATASET_MANIFEST.json        ← licence, source, credit
  DJI_0018.JPG … DJI_0035.JPG  ← the 18 frames
  brighton_beach.jpg           ← overview JPEG (skipped as unsupported)
  dsm.tif                      ← DSM raster (skipped as unsupported)
```

The product's discovery path is tolerant of this: supported images are ingested,
unsupported files are listed in the skipped count, and the run proceeds on the
frames that passed validation.
