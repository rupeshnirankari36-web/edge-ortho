"""Synthetic drone survey generator fixture for unit and integration testing."""

import math
from pathlib import Path

import cv2
import numpy as np
import piexif
import pytest
from PIL import Image


def _deg_to_dms_rational(deg_float: float):
    """Converts decimal degrees to EXIF rational format ((d, 1), (m, 1), (s*100, 100))."""
    deg = int(abs(deg_float))
    min_float = (abs(deg_float) - deg) * 60.0
    minute = int(min_float)
    sec = int(round((min_float - minute) * 60.0 * 100.0))
    return ((deg, 1), (minute, 1), (sec, 100))


def generate_synthetic_flight(
    output_dir: Path,
    num_rows: int = 2,
    num_cols: int = 3,
    base_lat: float = 34.0522,
    base_lon: float = -118.2437,
    altitude_m: float = 60.0,
    img_size: tuple[int, int] = (640, 480),  # (width, height)
) -> list[Path]:
    """Generates synthetic geotagged images simulating a drone flight over textured terrain."""
    output_dir.mkdir(parents=True, exist_ok=True)
    w, h = img_size

    # Base ground plane pattern: rich high-frequency textures for robust visual matching
    ground_w, ground_h = 2400, 2000
    np.random.seed(42)
    # Generate background with textured terrain noise and geometric features
    ground = np.zeros((ground_h, ground_w, 3), dtype=np.uint8)
    ground[:] = (40, 120, 60)  # Green terrain base

    # Draw grid roads and distinct visual landmarks
    for gy in range(0, ground_h, 150):
        cv2.line(ground, (0, gy), (ground_w, gy), (140, 140, 140), 12)
    for gx in range(0, ground_w, 150):
        cv2.line(ground, (gx, 0), (gx, ground_h), (140, 140, 140), 12)

    # Add high-contrast feature circles / buildings / rocks
    for _ in range(300):
        cx = int(np.random.randint(50, ground_w - 50))
        cy = int(np.random.randint(50, ground_h - 50))
        rad = int(np.random.randint(8, 25))
        col = (
            int(np.random.randint(100, 255)),
            int(np.random.randint(100, 255)),
            int(np.random.randint(100, 255)),
        )
        cv2.circle(ground, (cx, cy), rad, col, -1)
        cv2.rectangle(ground, (cx - rad, cy - rad), (cx + rad, cy + rad), (20, 20, 20), 2)

    generated_files = []
    # Approx 0.05 m/px GSD: 1 meter is ~20 pixels on ground
    # GPS spacing: 10 meters between consecutive frame centers (overlap ~75%)
    step_px_x = int(w * 0.4)
    step_px_y = int(h * 0.4)

    # Degrees per meter: 1 deg lat ~ 111,000 m; 1 deg lon ~ 92,000 m at 34 deg
    deg_per_m_lat = 1.0 / 111132.0
    deg_per_m_lon = 1.0 / (111132.0 * math.cos(math.radians(base_lat)))

    frame_count = 0
    for r in range(num_rows):
        for c in range(num_cols):
            frame_count += 1
            # Ground crop center
            center_x = 400 + c * step_px_x
            center_y = 400 + r * step_px_y

            # Crop subregion
            x0 = center_x - w // 2
            y0 = center_y - h // 2
            patch = ground[y0 : y0 + h, x0 : x0 + w].copy()

            # Add slight sensor noise
            noise = np.random.normal(0, 3, patch.shape).astype(np.int16)
            patch = np.clip(patch.astype(np.int16) + noise, 0, 255).astype(np.uint8)

            # GPS coordinates corresponding to ground center
            # Let center_x=400, center_y=400 be the base (base_lat, base_lon)
            offset_m_x = (center_x - 400) * 0.05
            offset_m_y = (center_y - 400) * 0.05
            frame_lat = base_lat - offset_m_y * deg_per_m_lat  # Y increases South
            frame_lon = base_lon + offset_m_x * deg_per_m_lon  # X increases East

            # Build EXIF dictionary
            lat_dms = _deg_to_dms_rational(frame_lat)
            lon_dms = _deg_to_dms_rational(frame_lon)

            gps_dict = {
                piexif.GPSIFD.GPSLatitudeRef: b"N" if frame_lat >= 0 else b"S",
                piexif.GPSIFD.GPSLatitude: lat_dms,
                piexif.GPSIFD.GPSLongitudeRef: b"E" if frame_lon >= 0 else b"W",
                piexif.GPSIFD.GPSLongitude: lon_dms,
                piexif.GPSIFD.GPSAltitudeRef: 0,
                piexif.GPSIFD.GPSAltitude: (int(altitude_m * 10), 10),
            }

            exif_dict = {
                "0th": {
                    piexif.ImageIFD.Make: b"DroneCo",
                    piexif.ImageIFD.Model: b"EdgeDrone-2000",
                    piexif.ImageIFD.DateTime: b"2026:10:09 10:00:00",
                },
                "Exif": {
                    piexif.ExifIFD.FocalLength: (45, 10),  # 4.5 mm
                    piexif.ExifIFD.FocalLengthIn35mmFilm: 24,  # 24 mm equiv
                },
                "GPS": gps_dict,
            }

            exif_bytes = piexif.dump(exif_dict)
            file_path = output_dir / f"frame_{frame_count:03d}.jpg"

            # Save JPEG with EXIF
            pil_img = Image.fromarray(cv2.cvtColor(patch, cv2.COLOR_BGR2RGB))
            pil_img.save(file_path, "JPEG", exif=exif_bytes, quality=95)
            generated_files.append(file_path)

    return generated_files


@pytest.fixture
def synthetic_survey(tmp_path: Path) -> Path:
    """Fixture providing a temporary directory of geotagged drone images."""
    data_dir = tmp_path / "synthetic_drone_images"
    generate_synthetic_flight(data_dir, num_rows=2, num_cols=3)
    return data_dir
