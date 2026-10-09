"""Robust EXIF and XMP metadata parser for aerial drone imagery."""

import re
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image

from .models import FrameRecord


def _convert_to_degrees(value) -> float | None:
    """Helper function to convert GPS coordinates stored as (deg, min, sec) into decimal degrees."""
    if value is None:
        return None
    try:
        # Handles tuples or lists of rationals or floats
        d = float(value[0])
        m = float(value[1])
        s = float(value[2])
        return d + (m / 60.0) + (s / 3600.0)
    except Exception:
        return None


def _parse_dji_xmp(image_path: Path) -> dict[str, float]:
    """Extract DJI drone metadata from XMP packet embedded in the file bytes."""
    meta = {}
    try:
        with open(image_path, "rb") as f:
            content = f.read(65536)  # Read first 64KB where XMP usually lives

        # Regex search for DJI XMP tags
        yaw_match = re.search(rb'FlightYawDegree="([+-]?\d+(?:\.\d+)?)"', content) or re.search(
            rb'drone-dji:FlightYawDegree="([+-]?\d+(?:\.\d+)?)"', content
        )
        if yaw_match:
            meta["yaw"] = float(yaw_match.group(1).decode("ascii"))

        pitch_match = re.search(rb'GimbalPitchDegree="([+-]?\d+(?:\.\d+)?)"', content) or re.search(
            rb'drone-dji:GimbalPitchDegree="([+-]?\d+(?:\.\d+)?)"', content
        )
        if pitch_match:
            meta["pitch"] = float(pitch_match.group(1).decode("ascii"))

        rel_alt_match = re.search(
            rb'RelativeAltitude="([+-]?\d+(?:\.\d+)?)"', content
        ) or re.search(rb'drone-dji:RelativeAltitude="([+-]?\d+(?:\.\d+)?)"', content)
        if rel_alt_match:
            meta["relative_altitude"] = float(rel_alt_match.group(1).decode("ascii"))
    except Exception:
        pass
    return meta


def extract_frame_metadata(image_path: Path) -> FrameRecord | None:
    """Reads EXIF and XMP metadata from an aerial image and returns a FrameRecord."""
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            exif_data = img._getexif() or {}

        named_exif: dict[str, Any] = {}
        for tag_id, value in exif_data.items():
            tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
            named_exif[tag_name] = value

        # Parse GPS Info
        gps_info = named_exif.get("GPSInfo", {})
        named_gps: dict[str, Any] = {}
        if isinstance(gps_info, dict):
            for tag_id, value in gps_info.items():
                tag_name = ExifTags.GPSTAGS.get(tag_id, str(tag_id))
                named_gps[tag_name] = value

        lat_raw = named_gps.get(
            "GPSLatitude", gps_info.get(2) if isinstance(gps_info, dict) else None
        )
        lat_ref = named_gps.get(
            "GPSLatitudeRef", gps_info.get(1, "N") if isinstance(gps_info, dict) else "N"
        )
        lon_raw = named_gps.get(
            "GPSLongitude", gps_info.get(4) if isinstance(gps_info, dict) else None
        )
        lon_ref = named_gps.get(
            "GPSLongitudeRef", gps_info.get(3, "E") if isinstance(gps_info, dict) else "E"
        )

        if isinstance(lat_ref, bytes):
            lat_ref = lat_ref.decode("ascii", "ignore")
        if isinstance(lon_ref, bytes):
            lon_ref = lon_ref.decode("ascii", "ignore")

        lat = _convert_to_degrees(lat_raw)
        lon = _convert_to_degrees(lon_raw)

        if lat is not None and str(lat_ref).strip().upper() == "S":
            lat = -lat
        if lon is not None and str(lon_ref).strip().upper() == "W":
            lon = -lon

        # Altitude
        alt_raw = named_gps.get(
            "GPSAltitude", gps_info.get(6, 0.0) if isinstance(gps_info, dict) else 0.0
        )
        try:
            alt = float(alt_raw)
        except Exception:
            alt = 0.0

        # Focal length
        focal_length = None
        fl_raw = named_exif.get("FocalLength")
        if fl_raw is not None:
            try:
                focal_length = float(fl_raw)
            except Exception:
                pass

        fl_35mm = named_exif.get("FocalLengthIn35mmFilm")
        try:
            fl_35mm = float(fl_35mm) if fl_35mm else None
        except Exception:
            fl_35mm = None

        camera_model = named_exif.get("Model")
        timestamp = named_exif.get("DateTimeOriginal") or named_exif.get("DateTime")

        # Parse XMP for DJI orientation (FlightYawDegree, GimbalPitchDegree, RelativeAltitude)
        xmp_meta = _parse_dji_xmp(image_path)
        yaw = xmp_meta.get("yaw")
        pitch = xmp_meta.get("pitch")
        if "relative_altitude" in xmp_meta and xmp_meta["relative_altitude"] > 0:
            alt = xmp_meta["relative_altitude"]

        # Normalize yaw to 0..360
        if yaw is not None:
            yaw = (yaw % 360.0 + 360.0) % 360.0

        if lat is None or lon is None:
            return None

        return FrameRecord(
            frame_id=image_path.stem,
            path=image_path.resolve(),
            lat=lat,
            lon=lon,
            altitude=alt,
            yaw=yaw,
            pitch=pitch,
            focal_length=focal_length,
            focal_length_35mm=fl_35mm,
            width=width,
            height=height,
            timestamp=str(timestamp) if timestamp else None,
            camera_model=str(camera_model) if camera_model else None,
        )
    except Exception:
        return None
