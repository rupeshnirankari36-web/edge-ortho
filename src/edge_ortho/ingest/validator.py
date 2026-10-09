"""Dataset and image ingestion validation."""

import logging
from pathlib import Path

from .exif import extract_frame_metadata
from .models import IngestionReport

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".tif", ".tiff", ".png"}


def ingest_and_validate_directory(
    input_dir: Path,
    pitch_nadir_threshold: float = -45.0,  # Gimbal pitch must be steeper than -45 deg if present
) -> IngestionReport:
    """Discovers images in input_dir, validates GPS/EXIF metadata, and logs rejections."""
    report = IngestionReport()

    if not input_dir.exists() or not input_dir.is_dir():
        logger.error(f"Input directory does not exist: {input_dir}")
        return report

    candidate_files = sorted(
        [p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS]
    )

    report.total_found = len(candidate_files)

    for file_path in candidate_files:
        meta = extract_frame_metadata(file_path)
        if meta is None:
            report.rejected_count += 1
            report.rejections.append(
                {
                    "file": file_path.name,
                    "reason": "Missing or corrupt EXIF GPS coordinates (Latitude/Longitude)",
                }
            )
            continue

        # Check pitch if available (non-nadir rejection)
        if meta.pitch is not None and meta.pitch > pitch_nadir_threshold:
            report.rejected_count += 1
            report.rejections.append(
                {
                    "file": file_path.name,
                    "reason": f"Non-nadir gimbal pitch ({meta.pitch:.1f}° > {pitch_nadir_threshold}°)",
                }
            )
            continue

        report.accepted_count += 1
        report.records.append(meta)

    return report
