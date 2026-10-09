from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from edge_ortho.geo_export import build_manifest, convert_to_cog, write_geotiff, write_manifest


def test_geotiff_has_runtime_crs_north_up_transform_and_nodata(tmp_path: Path):
    data = np.zeros((4, 32, 32), dtype=np.uint8)
    data[0, 5:20, 5:20] = 255
    tif = write_geotiff(
        data,
        tmp_path / "orthomosaic.tif",
        crs="EPSG:32643",
        transform=from_origin(500000, 2100000, 2, 2),
        nodata=0,
        block_size=16,
    )
    with rasterio.open(tif) as src:
        assert src.crs.to_epsg() == 32643
        assert src.transform.a == 2
        assert src.transform.e == -2
        assert src.count == 4
        assert src.nodata == 0
        assert src.is_tiled


def test_cog_and_manifest_are_derived_from_actual_raster(tmp_path: Path):
    data = np.ones((3, 512, 512), dtype=np.uint8) * 80
    tif = write_geotiff(
        data,
        tmp_path / "orthomosaic.tif",
        crs="EPSG:32643",
        transform=from_origin(500000, 2100000, 1, 1),
        block_size=256,
    )
    cog = convert_to_cog(tif, tmp_path / "orthomosaic_cog.tif")
    manifest = build_manifest(tif, dataset="fixture", source="synthetic", cog_path=cog)
    assert manifest.crs == "EPSG:32643"
    assert manifest.bounds == (500000.0, 2099488.0, 500512.0, 2100000.0)
    assert manifest.width == 512 and manifest.height == 512
    assert manifest.cog_bytes and manifest.cog_bytes > 0
    with rasterio.open(cog) as src:
        assert src.driver == "GTiff"  # GDAL exposes COG as a tiled GTiff reader
        assert src.is_tiled
        assert src.compression.value.lower() == "deflate"
        assert src.overviews(1)
    manifest_path = write_manifest(manifest, tmp_path / "manifest.json")
    assert '"dataset": "fixture"' in manifest_path.read_text()
