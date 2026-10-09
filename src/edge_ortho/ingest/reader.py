"""
EdgeOrtho – EXIF/XMP GPS metadata extraction.

Reads GPS tags from JPEG/TIFF drone images using exifread.
Returns structured per-image metadata including validation reasons.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from typing import Optional, Any
import numpy as np
import cv2
import exifread


@dataclass
class FrameRecord:
    frame_id: str
    path: str
    lat: float
    lon: float
    altitude_m: float = 100.0
    yaw_deg: Optional[float] = None
    focal_length_mm: Optional[float] = None
    width: int = 0
    height: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "path": self.path,
            "lat": self.lat,
            "lon": self.lon,
            "altitude_m": self.altitude_m,
            "yaw_deg": self.yaw_deg,
            "focal_length_mm": self.focal_length_mm,
            "width": self.width,
            "height": self.height,
        }


@dataclass
class ImageMeta:
    filename: str
    filepath: str
    file_bytes: int
    width: int = 0
    height: int = 0
    lat: Optional[float] = None
    lon: Optional[float] = None
    alt: Optional[float] = None
    yaw: Optional[float] = None
    focal_length_mm: Optional[float] = None
    orientation: int = 1
    has_gps: bool = False
    readable: bool = False
    rejection_reason: Optional[str] = None

    def to_frame_record(self) -> Optional[FrameRecord]:
        if not self.has_gps or self.lat is None or self.lon is None:
            return None
        frame_id = os.path.splitext(self.filename)[0]
        return FrameRecord(
            frame_id=frame_id,
            path=self.filepath,
            lat=self.lat,
            lon=self.lon,
            altitude_m=self.alt if self.alt is not None else 100.0,
            yaw_deg=self.yaw,
            focal_length_mm=self.focal_length_mm,
            width=self.width,
            height=self.height,
        )


def _ifd_value(value) -> float:
    """Convert IFD rational to float."""
    if hasattr(value, "num") and hasattr(value, "den"):
        return float(value.num) / float(value.den)
    return float(value)


def _to_degrees(values) -> float:
    d = _ifd_value(values[0])
    m = _ifd_value(values[1])
    s = _ifd_value(values[2])
    return d + m / 60.0 + s / 3600.0


def extract_gps(filepath: str) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Extract (lat, lon, alt) or (None, None, None) if no GPS tags."""
    try:
        with open(filepath, "rb") as fh:
            tags = exifread.process_file(fh, details=False, stop_tag="GPS GPSAltitude")
        lat_tag = tags.get("GPS GPSLatitude")
        lon_tag = tags.get("GPS GPSLongitude")
        if lat_tag is None or lon_tag is None:
            return None, None, None

        lat = _to_degrees(lat_tag.values)
        lon = _to_degrees(lon_tag.values)

        lat_ref = str(tags.get("GPS GPSLatitudeRef", "N"))
        lon_ref = str(tags.get("GPS GPSLongitudeRef", "E"))
        if lat_ref not in ("N", "S"):
            lat_ref = "N"
        if lon_ref not in ("E", "W"):
            lon_ref = "E"

        if lat_ref == "S":
            lat = -lat
        if lon_ref == "W":
            lon = -lon

        alt: Optional[float] = None
        alt_tag = tags.get("GPS GPSAltitude")
        if alt_tag:
            try:
                alt = _ifd_value(alt_tag.values[0])
            except Exception:
                pass

        return lat, lon, alt
    except Exception:
        return None, None, None


def extract_extended_metadata(filepath: str) -> dict[str, Any]:
    """Extract GPS, camera orientation, and focal length from EXIF."""
    meta: dict[str, Any] = {
        "lat": None,
        "lon": None,
        "alt": None,
        "yaw": None,
        "focal_length_mm": None,
        "orientation": 1,
    }
    try:
        with open(filepath, "rb") as fh:
            tags = exifread.process_file(fh, details=False)

        lat_tag = tags.get("GPS GPSLatitude")
        lon_tag = tags.get("GPS GPSLongitude")
        if lat_tag is not None and lon_tag is not None:
            lat = _to_degrees(lat_tag.values)
            lon = _to_degrees(lon_tag.values)
            lat_ref = str(tags.get("GPS GPSLatitudeRef", "N"))
            lon_ref = str(tags.get("GPS GPSLongitudeRef", "E"))
            if lat_ref == "S":
                lat = -lat
            if lon_ref == "W":
                lon = -lon
            meta["lat"] = lat
            meta["lon"] = lon

            alt_tag = tags.get("GPS GPSAltitude")
            if alt_tag:
                try:
                    meta["alt"] = _ifd_value(alt_tag.values[0])
                except Exception:
                    pass

        orient_tag = tags.get("Image Orientation")
        if orient_tag and orient_tag.values:
            try:
                meta["orientation"] = int(orient_tag.values[0])
            except Exception:
                meta["orientation"] = 1

        focal_tag = tags.get("EXIF FocalLength")
        if focal_tag and focal_tag.values:
            try:
                meta["focal_length_mm"] = _ifd_value(focal_tag.values[0])
            except Exception:
                pass

        track_tag = tags.get("GPS GPSTrack")
        if track_tag and track_tag.values:
            try:
                meta["yaw"] = _ifd_value(track_tag.values[0])
            except Exception:
                pass

    except Exception:
        pass

    return meta


def apply_exif_orientation(image: np.ndarray, orientation: int) -> np.ndarray:
    """Rotate / flip image to correct for EXIF orientation tag."""
    if orientation == 2:
        return cv2.flip(image, 1)
    elif orientation == 3:
        return cv2.rotate(image, cv2.ROTATE_180)
    elif orientation == 4:
        return cv2.flip(image, 0)
    elif orientation == 5:
        return cv2.flip(cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE), 0)
    elif orientation == 6:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    elif orientation == 7:
        return cv2.flip(cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE), 0)
    elif orientation == 8:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image


def load_frame_for_matching(
    filepath: str,
    target_pixels: int = 600_000,
    grayscale: bool = True,
    orientation: int = 1,
) -> tuple[Optional[np.ndarray], float]:
    """
    Safely load an image, correct EXIF orientation, and downscale to near target_pixels (~0.6 MP).
    Returns (downscaled_image, scale_factor).
    Never keeps full-resolution image in memory after this returns.
    """
    try:
        flags = cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR
        full_img = cv2.imread(filepath, flags)
        if full_img is None:
            return None, 1.0

        if orientation > 1:
            full_img = apply_exif_orientation(full_img, orientation)

        h, w = full_img.shape[:2]
        pixels = h * w
        if pixels <= target_pixels:
            return full_img, 1.0

        import math
        scale = math.sqrt(target_pixels / float(pixels))
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        resized = cv2.resize(full_img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        del full_img
        return resized, scale
    except Exception:
        return None, 1.0


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".tif", ".tiff"}


def ingest_folder(folder_path: str) -> list[ImageMeta]:
    """Scan folder, read each image metadata, extract GPS. Returns list of ImageMeta."""
    results: list[ImageMeta] = []

    for fname in sorted(os.listdir(folder_path)):
        ext = os.path.splitext(fname)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue

        fpath = os.path.join(folder_path, fname)
        fsize = os.path.getsize(fpath)
        meta = ImageMeta(filename=fname, filepath=fpath, file_bytes=fsize)

        ext_meta = extract_extended_metadata(fpath)
        meta.lat = ext_meta["lat"]
        meta.lon = ext_meta["lon"]
        meta.alt = ext_meta["alt"]
        meta.yaw = ext_meta["yaw"]
        meta.focal_length_mm = ext_meta["focal_length_mm"]
        meta.orientation = ext_meta["orientation"]

        # Check readability via OpenCV
        img = cv2.imread(fpath)
        if img is None:
            meta.rejection_reason = "unreadable_file"
            results.append(meta)
            continue

        meta.readable = True
        h, w = img.shape[:2]
        del img

        if meta.orientation in (5, 6, 7, 8):
            meta.width, meta.height = h, w
        else:
            meta.width, meta.height = w, h

        if meta.lat is not None and meta.lon is not None:
            meta.has_gps = True
        else:
            meta.rejection_reason = "no_gps_metadata"

        results.append(meta)

    return results
