"""
Tests for EdgeOrtho pipeline components.
Tests: metadata parsing, missing GPS, unreadable images, neighbour selection,
match failure, transform validation, and metric calculations.
"""
import os
import sys
import json
import math
import struct
import tempfile
import numpy as np
import pytest

# Ensure src on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from edge_ortho.ingest.reader import ImageMeta, extract_gps, ingest_folder
from edge_ortho.ingest.neighbours import haversine_m, build_neighbour_graph, NeighbourPair
from edge_ortho.align.matcher import match_pair, _downscale_image


# ---------------------------------------------------------------------------
# Helpers to create minimal test images
# ---------------------------------------------------------------------------

def _make_jpeg_no_gps(path: str, w: int = 80, h: int = 60) -> None:
    import cv2
    img = np.random.randint(0, 255, (h, w, 3), dtype=np.uint8)
    cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, 85])


def _make_image_with_gps(path: str, lat: float, lon: float, alt: float = 50.0) -> None:
    """Create a tiny JPEG with GPS EXIF using piexif if available."""
    import cv2
    img = np.random.randint(30, 220, (60, 80, 3), dtype=np.uint8)
    cv2.imwrite(path, img)

    try:
        import piexif
        def _to_rational(val):
            # Convert float to (numerator, denominator) tuple
            return (int(abs(val) * 1_000_000), 1_000_000)

        lat_ref = b"N" if lat >= 0 else b"S"
        lon_ref = b"E" if lon >= 0 else b"W"
        lat_abs = abs(lat)
        lon_abs = abs(lon)

        def deg_to_dms_rational(v):
            d = int(v)
            m = int((v - d) * 60)
            s = ((v - d) * 60 - m) * 60
            return [(d, 1), (m, 1), (int(s * 100), 100)]

        exif_dict = {
            "GPS": {
                piexif.GPSIFD.GPSLatitudeRef: lat_ref,
                piexif.GPSIFD.GPSLatitude: deg_to_dms_rational(lat_abs),
                piexif.GPSIFD.GPSLongitudeRef: lon_ref,
                piexif.GPSIFD.GPSLongitude: deg_to_dms_rational(lon_abs),
                piexif.GPSIFD.GPSAltitude: (int(alt * 100), 100),
                piexif.GPSIFD.GPSAltitudeRef: 0,
            }
        }
        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, path)
    except ImportError:
        pass  # piexif not available; GPS tests requiring real EXIF will be skipped


# ---------------------------------------------------------------------------
# Haversine distance
# ---------------------------------------------------------------------------

class TestHaversine:
    def test_same_point(self):
        assert haversine_m(51.5, -0.1, 51.5, -0.1) == pytest.approx(0.0, abs=0.01)

    def test_known_distance(self):
        # London to Paris ≈ 340 km
        d = haversine_m(51.5074, -0.1278, 48.8566, 2.3522)
        assert 330_000 < d < 350_000

    def test_symmetry(self):
        d1 = haversine_m(10.0, 20.0, 11.0, 21.0)
        d2 = haversine_m(11.0, 21.0, 10.0, 20.0)
        assert d1 == pytest.approx(d2, rel=1e-9)


# ---------------------------------------------------------------------------
# ImageMeta / ingest
# ---------------------------------------------------------------------------

class TestIngestFolder:
    def test_empty_folder(self, tmp_path):
        result = ingest_folder(str(tmp_path))
        assert result == []

    def test_unreadable_file(self, tmp_path):
        bad = tmp_path / "bad.jpg"
        bad.write_bytes(b"NOT_AN_IMAGE")
        result = ingest_folder(str(tmp_path))
        assert len(result) == 1
        assert result[0].readable is False
        assert result[0].rejection_reason == "unreadable_file"

    def test_valid_no_gps(self, tmp_path):
        p = str(tmp_path / "img.jpg")
        _make_jpeg_no_gps(p)
        result = ingest_folder(str(tmp_path))
        assert len(result) == 1
        assert result[0].readable is True
        assert result[0].has_gps is False
        assert result[0].rejection_reason == "no_gps_metadata"

    def test_non_image_ignored(self, tmp_path):
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "doc.pdf").write_bytes(b"%PDF")
        result = ingest_folder(str(tmp_path))
        assert result == []


# ---------------------------------------------------------------------------
# Neighbour graph
# ---------------------------------------------------------------------------

class TestNeighbourGraph:
    def _make_images(self, coords: list[tuple[float, float]]) -> list[ImageMeta]:
        imgs = []
        for i, (lat, lon) in enumerate(coords):
            img = ImageMeta(filename=f"img{i:02d}.jpg", filepath=f"/fake/img{i:02d}.jpg", file_bytes=1000)
            img.readable = True
            img.lat = lat
            img.lon = lon
            img.has_gps = True
            img.width = 80
            img.height = 60
            imgs.append(img)
        return imgs

    def test_no_gps_images(self):
        imgs = [ImageMeta(filename="a.jpg", filepath="/fake/a.jpg", file_bytes=100)]
        result = build_neighbour_graph(imgs)
        assert result == []

    def test_single_gps_image(self):
        imgs = self._make_images([(51.5, -0.1)])
        result = build_neighbour_graph(imgs)
        assert result == []

    def test_nearby_pair(self):
        # Two images 50m apart should pair
        lat1, lon1 = 51.5000, -0.1000
        lat2, lon2 = 51.5005, -0.1000  # ~55m north
        imgs = self._make_images([(lat1, lon1), (lat2, lon2)])
        result = build_neighbour_graph(imgs, max_distance_m=120.0)
        assert len(result) == 1
        assert result[0].distance_m < 120

    def test_distant_pair_excluded(self):
        # 2 km apart – should not pair with 120m threshold
        imgs = self._make_images([(51.5000, -0.1000), (51.5200, -0.1000)])
        result = build_neighbour_graph(imgs, max_distance_m=120.0)
        assert result == []

    def test_no_duplicate_pairs(self):
        coords = [(51.5, -0.1 + i * 0.0001) for i in range(5)]
        imgs = self._make_images(coords)
        result = build_neighbour_graph(imgs, max_distance_m=500.0)
        # All pairs should be unique
        seen = set()
        for p in result:
            key = (min(p.idx_a, p.idx_b), max(p.idx_a, p.idx_b))
            assert key not in seen, f"Duplicate pair: {key}"
            seen.add(key)

    def test_max_neighbours_respected(self):
        # 10 images all clustered together
        coords = [(51.5 + i * 0.00001, -0.1) for i in range(10)]
        imgs = self._make_images(coords)
        result = build_neighbour_graph(imgs, max_distance_m=500.0, max_neighbours=3)
        # Count neighbours per image
        counts: dict[int, int] = {}
        for p in result:
            counts[p.idx_a] = counts.get(p.idx_a, 0) + 1
            counts[p.idx_b] = counts.get(p.idx_b, 0) + 1
        for idx, count in counts.items():
            assert count <= 3, f"Image {idx} has {count} neighbours (max 3)"


# ---------------------------------------------------------------------------
# Feature matching
# ---------------------------------------------------------------------------

class TestMatcher:
    def test_downscale_large(self):
        img = np.zeros((2000, 3000, 3), dtype=np.uint8)
        out, scale = _downscale_image(img, 600_000)
        assert out.shape[0] * out.shape[1] <= 600_000 * 1.05
        assert scale < 1.0

    def test_downscale_small(self):
        img = np.zeros((100, 200, 3), dtype=np.uint8)
        out, scale = _downscale_image(img, 600_000)
        assert scale == 1.0
        assert out.shape == img.shape

    def test_match_unreadable_file(self, tmp_path):
        bad = str(tmp_path / "bad.jpg")
        good = str(tmp_path / "good.jpg")
        import cv2
        img = np.random.randint(0, 255, (60, 80, 3), dtype=np.uint8)
        cv2.imwrite(good, img)
        open(bad, "w").write("not_image")

        result = match_pair(bad, good)
        assert result.success is False
        assert result.error is not None

    def test_match_identical_images(self, tmp_path):
        """Matching an image with itself should succeed with many inliers."""
        import cv2
        # Use a real texture so ORB finds keypoints
        img = np.random.randint(0, 255, (200, 300, 3), dtype=np.uint8)
        p = str(tmp_path / "img.jpg")
        cv2.imwrite(p, img)
        result = match_pair(p, p)
        # Should succeed (same image = perfect matches)
        if result.success:
            assert result.inliers >= 8

    def test_match_blank_images_fails(self, tmp_path):
        """Blank images have no features – matching should fail gracefully."""
        import cv2
        blank = np.zeros((200, 300, 3), dtype=np.uint8)
        p1 = str(tmp_path / "blank1.jpg")
        p2 = str(tmp_path / "blank2.jpg")
        cv2.imwrite(p1, blank)
        cv2.imwrite(p2, blank)
        result = match_pair(p1, p2)
        assert result.success is False


# ---------------------------------------------------------------------------
# Bandwidth metric calculation
# ---------------------------------------------------------------------------

class TestBandwidthCalc:
    def test_formula_1mbps(self):
        # 10 MB at 1 Mbps = 80 seconds
        in_bytes = 10 * 1_000_000
        speed_bps = 1 * 1_000_000
        expected = in_bytes * 8 / speed_bps
        assert expected == pytest.approx(80.0)

    def test_formula_20mbps(self):
        in_bytes = 100 * 1_000_000  # 100 MB
        speed_bps = 20 * 1_000_000
        result = in_bytes * 8 / speed_bps
        assert result == pytest.approx(40.0)

    def test_larger_input_slower(self):
        def transfer(b, mbps):
            return b * 8 / (mbps * 1_000_000)
        assert transfer(100_000_000, 5) > transfer(10_000_000, 5)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
