import pytest

from edge_ortho.geospatial import (
    Bounds,
    Canvas,
    GeoPoint,
    bounds_from_projected,
    utm_epsg,
    validate_points,
)


def test_utm_epsg_northern_and_southern_hemispheres():
    assert utm_epsg(GeoPoint(19.0, 73.0)) == 32643
    assert utm_epsg(GeoPoint(-33.0, 151.0)) == 32756


def test_invalid_coordinates_are_rejected():
    with pytest.raises(ValueError):
        GeoPoint(91, 0).validate()
    with pytest.raises(ValueError):
        validate_points([])


def test_projected_bounds_and_canvas_round_trip():
    bounds = bounds_from_projected([(100.0, 200.0), (140.0, 240.0)], padding_m=5)
    assert bounds == Bounds(95.0, 195.0, 145.0, 245.0)
    canvas = Canvas(bounds, pixel_size_m=1.0, width_px=50, height_px=50)
    col, row = canvas.world_to_pixel(120.0, 220.0)
    assert (col, row) == (25.0, 25.0)
    assert canvas.pixel_to_world(col, row) == (120.0, 220.0)


def test_invalid_bounds_and_canvas_fail_fast():
    with pytest.raises(ValueError):
        Bounds(1, 2, 1, 3).validate()
    with pytest.raises(ValueError):
        Canvas(Bounds(0, 0, 1, 1), 0, 1, 1).validate()
