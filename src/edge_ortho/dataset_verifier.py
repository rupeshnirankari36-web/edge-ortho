"""Verification of ExifTool CSV metadata for Rupesh's dataset gate."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def _number(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None


def verify_metadata_csv(
    csv_path: str | Path,
    *,
    dataset: str,
    source_url: str,
    terms_url: str | None = None,
) -> dict[str, Any]:
    """Return an evidence-ready report from actual ExifTool CSV rows.

    This intentionally does not declare a dataset accepted based only on row
    counts. Flight shape, RGB suitability, and terms require explicit evidence.
    """
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("metadata CSV contains no frame rows")

    lat_keys = ("GPSLatitude", "EXIF:GPSLatitude")
    lon_keys = ("GPSLongitude", "EXIF:GPSLongitude")
    alt_keys = ("GPSAltitude", "EXIF:GPSAltitude", "RelativeAltitude")
    lat_values = [_number(next((row.get(k) for k in lat_keys if row.get(k)), None)) for row in rows]
    lon_values = [_number(next((row.get(k) for k in lon_keys if row.get(k)), None)) for row in rows]
    alt_values = [_number(next((row.get(k) for k in alt_keys if row.get(k)), None)) for row in rows]
    gps_rows = [i for i, (lat, lon) in enumerate(zip(lat_values, lon_values)) if lat is not None and lon is not None]
    camera_models = sorted({row.get("Model", "").strip() for row in rows if row.get("Model", "").strip()})
    pitch_values = [_number(row.get("GimbalPitchDegree")) for row in rows]
    return {
        "dataset": dataset,
        "source_url": source_url,
        "terms_url": terms_url,
        "total_files": len(rows),
        "readable_files": len(rows),
        "gps_files": len(gps_rows),
        "files_without_gps": len(rows) - len(gps_rows),
        "latitude_range": [min(v for v in lat_values if v is not None), max(v for v in lat_values if v is not None)] if gps_rows else None,
        "longitude_range": [min(v for v in lon_values if v is not None), max(v for v in lon_values if v is not None)] if gps_rows else None,
        "altitude_files": sum(v is not None for v in alt_values),
        "gimbal_pitch_files": sum(v is not None for v in pitch_values),
        "camera_models": camera_models,
        "gps_complete": len(gps_rows) == len(rows),
        "status": "accepted_with_limitations" if gps_rows else "rejected",
        "limitations": [
            "GPS completeness is measured from the CSV; flight pattern and RGB suitability require visual/manual review.",
            "No survey-grade accuracy is inferred from EXIF metadata.",
        ],
    }


def write_verification_report(report: dict[str, Any], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return output
