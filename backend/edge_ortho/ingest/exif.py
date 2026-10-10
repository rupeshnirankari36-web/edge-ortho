"""EXIF / XMP metadata extraction for drone imagery.

Design rules taken from the brief:

* "Reads and validates EXIF/XMP metadata." - both sources are read.
* "Missing GPS metadata -> Reject and report the frame" - a frame without a
  usable latitude/longitude is rejected, never silently defaulted.
* Values that are genuinely absent stay ``None``. We do not substitute a
  default altitude, yaw or focal length.

DJI stores useful flight metadata in an XMP packet that most generic EXIF
readers ignore (``drone-dji:GpsLatitude``, ``RelativeAltitude``,
``GimbalYawDegree``, ``GimbalPitchDegree``). We parse that packet directly so
the pipeline can prefer *above-ground* altitude for the GSD estimate and can
check whether the capture is actually nadir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# TIFF tag numbers are used directly: the names moved between Pillow's
# TiffImagePlugin and ExifTags modules across releases and the ids are stable.
_TIFF_MAKE = 271
_TIFF_MODEL = 272

try:
    import piexif
except Exception:  # pragma: no cover - optional
    piexif = None  # type: ignore[assignment]

_XMP_START = re.compile(rb"<x:xmpmeta", re.IGNORECASE)
_XMP_END = re.compile(rb"</x:xmpmeta>", re.IGNORECASE)
_XMP_ATTR = re.compile(r'([A-Za-z0-9_.:-]+)\s*=\s*"([^"]*)"')

#: Scan the head of a file for XMP. Adobe/DJI put the packet in APP1, but some
#: TIFF writers append it later, so we allow a generous head window.
_XMP_SCAN_BYTES = 512 * 1024


@dataclass
class ImageMetadata:
    """Everything we could extract. ``None`` means 'not present in the file'."""

    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float | None = None  # above ground when available
    absolute_altitude_m: float | None = None
    altitude_source: str | None = None  # exif_gps | xmp_relative | xmp_absolute
    yaw_deg: float | None = None
    yaw_source: str | None = None  # xmp_gimbal | exif_direction
    pitch_deg: float | None = None
    roll_deg: float | None = None
    width: int | None = None
    height: int | None = None
    make: str | None = None
    model: str | None = None
    focal_length_mm: float | None = None
    focal_length_35mm: float | None = None
    sensor_width_mm: float | None = None
    captured_at: str | None = None
    xmp: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    error_code: str | None = None  # maps to contracts.RejectReason
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _to_float(value) -> float | None:
    try:
        if isinstance(value, (tuple, list)) and len(value) == 2:
            num, den = value
            if den in (0, None):
                return None
            return float(num) / float(den)
        if isinstance(value, bytes):
            value = value.decode("ascii", "replace")
        if isinstance(value, str):
            value = value.strip().strip("+")
            if not value:
                return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dms_to_deg(dms, ref) -> float | None:
    """Convert an EXIF (d, m, s) rational triple plus hemisphere ref to degrees."""
    try:
        if dms is None or len(dms) != 3:
            return None
        parts = [_to_float(v) for v in dms]
        if any(p is None for p in parts):
            return None
        deg = parts[0] + parts[1] / 60.0 + parts[2] / 3600.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if isinstance(ref, bytes):
        ref = ref.decode("ascii", "replace")
    ref = (ref or "").strip().upper()
    if ref in ("S", "W"):
        deg = -deg
    return deg


def _clean_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    text = str(value).replace("\x00", " ").strip()
    return text or None


# ---------------------------------------------------------------------------
# XMP
# ---------------------------------------------------------------------------


def parse_xmp_packet(text: str) -> dict[str, str]:
    """Pull the attribute map out of an XMP string (namespace prefixes kept)."""
    out: dict[str, str] = {}
    for key, value in _XMP_ATTR.findall(text):
        out[key] = value
    return out


def read_xmp(path: Path) -> dict[str, str]:
    """Read the raw XMP packet from a file without decoding the image."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(_XMP_SCAN_BYTES)
    except OSError:
        return {}
    start = _XMP_START.search(head)
    if not start:
        return {}
    end = _XMP_END.search(head, start.start())
    raw = head[start.start() : end.end()] if end else head[start.start() :]
    return parse_xmp_packet(raw.decode("utf-8", "replace"))


def _xmp_number(xmp: dict[str, str], key: str) -> float | None:
    for candidate in (f"drone-dji:{key}", f"drone-dji:{key}Degree", key):
        if candidate in xmp:
            return _to_float(xmp[candidate])
    return None


# ---------------------------------------------------------------------------
# EXIF
# ---------------------------------------------------------------------------


def _read_exif_jpeg(path: Path) -> tuple[dict, dict]:
    """Return (exif_gps_dict, exif_main_dict) for a JPEG using piexif."""
    if piexif is None:
        return {}, {}
    try:
        data = piexif.load(str(path))
    except Exception:
        return {}, {}
    return data.get("GPS", {}) or {}, {
        "0th": data.get("0th", {}) or {},
        "Exif": data.get("Exif", {}) or {},
    }


def _read_exif_pillow(path: Path) -> tuple[dict, dict]:
    """Fallback / TIFF path: use Pillow's EXIF reader."""
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            if not exif:
                return {}, {}
            gps: dict = {}
            try:
                gps_ifd = exif.get_ifd(0x8825)  # GPSInfo
                gps = dict(gps_ifd) if gps_ifd else {}
            except Exception:
                gps = {}
            exif_ifd: dict = {}
            try:
                exif_ifd = dict(exif.get_ifd(0x8769))  # ExifIFD
            except Exception:
                exif_ifd = {}
            return gps, {"0th": dict(exif), "Exif": exif_ifd}
    except (UnidentifiedImageError, OSError):
        return {}, {}


# Pillow/EXIF tag numbers used when piexif is unavailable.
_GPS_LAT, _GPS_LAT_REF = 2, 1
_GPS_LON, _GPS_LON_REF = 4, 3
_GPS_ALT, _GPS_ALT_REF, _GPS_ALT_REF_BYTE = 6, 5, 5
_GPS_IMG_DIRECTION, _GPS_IMG_DIRECTION_REF = 17, 16


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def read_image_metadata(path: str | Path, read_xmp_packet: bool = True) -> ImageMetadata:
    """Extract all available metadata for one image file.

    Never raises for a bad file: the failure is described in ``error`` and
    ``error_code`` so the caller can put it in the accepted/rejected report.
    """
    path = Path(path)
    meta = ImageMetadata()

    try:
        size_bytes = path.stat().st_size
    except OSError as exc:
        meta.error = f"cannot stat file: {exc}"
        meta.error_code = "unreadable"
        return meta
    if size_bytes == 0:
        meta.error = "file is 0 bytes"
        meta.error_code = "zero_size"
        return meta

    # --- pixel dimensions (header read only, no full decode) --------------
    try:
        with Image.open(path) as im:
            meta.width, meta.height = im.size
            fmt = (im.format or "").upper()
            meta.xmp = {}
            if fmt == "TIFF":
                tiff_tags = getattr(im, "tag_v2", None)
                if tiff_tags:
                    meta.make = _clean_text(tiff_tags.get(_TIFF_MAKE))
                    meta.model = _clean_text(tiff_tags.get(_TIFF_MODEL))
    except UnidentifiedImageError:
        meta.error = "not a readable image"
        meta.error_code = "decode_failed"
        return meta
    except OSError as exc:
        meta.error = f"cannot open image: {exc}"
        meta.error_code = "unreadable"
        return meta

    # --- EXIF -------------------------------------------------------------
    if path.suffix.lower() in (".jpg", ".jpeg"):
        gps, main = _read_exif_jpeg(path)
        if not gps and not main:
            gps, main = _read_exif_pillow(path)
    else:
        gps, main = _read_exif_pillow(path)

    zth = main.get("0th", {})
    exf = main.get("Exif", {})

    if piexif is not None and gps:
        lat = _dms_to_deg(gps.get(piexif.GPSIFD.GPSLatitude), gps.get(piexif.GPSIFD.GPSLatitudeRef))
        lon = _dms_to_deg(
            gps.get(piexif.GPSIFD.GPSLongitude), gps.get(piexif.GPSIFD.GPSLongitudeRef)
        )
        alt = _to_float(gps.get(piexif.GPSIFD.GPSAltitude))
        alt_ref = gps.get(piexif.GPSIFD.GPSAltitudeRef, 0)
        direction = _to_float(gps.get(piexif.GPSIFD.GPSImgDirection))
    else:
        lat = _dms_to_deg(gps.get(_GPS_LAT), gps.get(_GPS_LAT_REF))
        lon = _dms_to_deg(gps.get(_GPS_LON), gps.get(_GPS_LON_REF))
        alt = _to_float(gps.get(_GPS_ALT))
        alt_ref = gps.get(_GPS_ALT_REF_BYTE, 0)
        direction = _to_float(gps.get(_GPS_IMG_DIRECTION))

    if alt is not None:
        try:
            if int(alt_ref) == 1:
                alt = -alt
        except (TypeError, ValueError):
            pass

    meta.latitude, meta.longitude = lat, lon
    if alt is not None:
        meta.altitude_m = alt
        meta.absolute_altitude_m = alt
        meta.altitude_source = "exif_gps"
    if direction is not None:
        meta.yaw_deg = direction % 360.0
        meta.yaw_source = "exif_direction"

    if piexif is not None:
        focal = _to_float(exf.get(piexif.ExifIFD.FocalLength))
        focal35 = _to_float(exf.get(piexif.ExifIFD.FocalLengthIn35mmFilm))
        captured = _clean_text(exf.get(piexif.ExifIFD.DateTimeOriginal))
        make = _clean_text(zth.get(piexif.ImageIFD.Make))
        model = _clean_text(zth.get(piexif.ImageIFD.Model))
    else:
        focal = _to_float(exf.get(0x920A))
        focal35 = _to_float(exf.get(0xA405))
        captured = _clean_text(exf.get(0x9003))
        make = _clean_text(zth.get(0x010F))
        model = _clean_text(zth.get(0x0110))

    meta.make = meta.make or make
    meta.model = meta.model or model
    meta.focal_length_mm = focal
    meta.focal_length_35mm = focal35
    if captured:
        meta.captured_at = captured

    # --- XMP (DJI adds AGL altitude, gimbal angles, XMP GPS) --------------
    if read_xmp_packet:
        xmp = read_xmp(path)
        if xmp:
            meta.xmp = xmp
            if lat is None:
                x_lat = _xmp_number(xmp, "GpsLatitude") or _xmp_number(xmp, "Latitude")
                x_lon = _xmp_number(xmp, "GpsLongitude") or _xmp_number(xmp, "Longitude")
                if x_lat is not None and x_lon is not None:
                    meta.latitude, meta.longitude = x_lat, x_lon
            rel = _xmp_number(xmp, "RelativeAltitude")
            if rel is not None:
                # Above-ground altitude: the right input for a GSD estimate.
                meta.altitude_m = rel
                meta.altitude_source = "xmp_relative"
            abs_alt = _xmp_number(xmp, "AbsoluteAltitude")
            if abs_alt is not None:
                meta.absolute_altitude_m = abs_alt
                if meta.altitude_source is None:
                    meta.altitude_source = "xmp_absolute"
            gimbal_yaw = _xmp_number(xmp, "GimbalYawDegree")
            if gimbal_yaw is not None:
                meta.yaw_deg = gimbal_yaw % 360.0
                meta.yaw_source = "xmp_gimbal"
            meta.pitch_deg = _xmp_number(xmp, "GimbalPitchDegree")
            meta.roll_deg = _xmp_number(xmp, "GimbalRollDegree")
            if not meta.model:
                meta.model = xmp.get("tiff:Model")
            if not meta.make:
                meta.make = xmp.get("tiff:Make")

    if meta.altitude_source in ("exif_gps", "xmp_absolute"):
        # GPSAltitude and AbsoluteAltitude are heights above mean sea level. Using
        # one as if it were height above ground would inflate the ground sampling
        # distance by the terrain elevation, so the frame is marked as approximate
        # instead of being silently treated as AGL.
        meta.warnings.append("absolute_altitude_only")

    return meta


def is_nadir(pitch_deg: float | None, tolerance_deg: float = 12.0) -> bool | None:
    """True/False when pitch is known, ``None`` when it is not."""
    if pitch_deg is None:
        return None
    return abs(abs(pitch_deg) - 90.0) <= tolerance_deg
