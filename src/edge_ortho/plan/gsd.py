"""Ground Sampling Distance (GSD) and flight heading estimation."""

import math
from collections.abc import Sequence

from ..ingest.models import FrameRecord

# Typical 1/2.3", 1/1.3", or 1" sensor width fallback (mm)
DEFAULT_SENSOR_WIDTH_MM = 6.17


def estimate_record_gsd(
    record: FrameRecord,
    default_focal_mm: float = 4.5,
    default_sensor_width_mm: float = DEFAULT_SENSOR_WIDTH_MM,
) -> float:
    """
    Estimates GSD in meters/pixel using sensor geometry:
    GSD = (Altitude_m * SensorWidth_mm) / (FocalLength_mm * ImageWidth_px)
    """
    altitude = max(record.altitude, 5.0)  # minimum 5m safety clamp
    width_px = max(record.width, 100)

    # If 35mm equivalent focal length is given, sensor width equivalent is 36.0mm
    if record.focal_length_35mm and record.focal_length_35mm > 0:
        focal_mm = record.focal_length_35mm
        sensor_width_mm = 36.0
    elif record.focal_length and record.focal_length > 0:
        focal_mm = record.focal_length
        sensor_width_mm = default_sensor_width_mm
    else:
        focal_mm = default_focal_mm
        sensor_width_mm = default_sensor_width_mm

    # (Altitude in meters * sensor_width in mm) / (focal in mm * width in pixels)
    # The mm units cancel out, yielding meters per pixel directly
    gsd = (altitude * sensor_width_mm) / (focal_mm * width_px)
    # Safety clamp: drone GSD typically 0.005m - 0.5m per pixel
    gsd = max(0.005, min(0.5, gsd))
    return gsd


def populate_gsd_and_headings(records: Sequence[FrameRecord]) -> None:
    """Populates GSD and computes GPS flight trajectory headings if yaw is absent."""
    for r in records:
        r.gsd_m = estimate_record_gsd(r)

    # Populate yaw if missing by calculating tangent vector between successive frames
    for i in range(len(records)):
        if records[i].yaw is None:
            # Look at neighbor ahead or behind
            if i + 1 < len(records) and records[i].utm_easting and records[i + 1].utm_easting:
                de = records[i + 1].utm_easting - records[i].utm_easting
                dn = records[i + 1].utm_northing - records[i].utm_northing
                dist = math.hypot(de, dn)
                if dist > 2.0:
                    # Heading angle clockwise from North (degrees)
                    angle_deg = math.degrees(math.atan2(de, dn))
                    records[i].yaw = (angle_deg + 360.0) % 360.0
            elif i > 0 and records[i].utm_easting and records[i - 1].utm_easting:
                de = records[i].utm_easting - records[i - 1].utm_easting
                dn = records[i].utm_northing - records[i - 1].utm_northing
                dist = math.hypot(de, dn)
                if dist > 2.0:
                    angle_deg = math.degrees(math.atan2(de, dn))
                    records[i].yaw = (angle_deg + 360.0) % 360.0

            if records[i].yaw is None:
                records[i].yaw = 0.0  # Default North-facing if single stationary frame
