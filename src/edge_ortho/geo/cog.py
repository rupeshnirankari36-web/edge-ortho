"""Cloud Optimized GeoTIFF (COG) generation with internal overview pyramids."""

import logging
from pathlib import Path

from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles

logger = logging.getLogger(__name__)


def convert_to_cog(
    input_geotiff_path: Path,
    output_cog_path: Path,
    overview_resampling: str = "average",
) -> Path | None:
    """Converts a standard GeoTIFF into a Cloud-Optimized GeoTIFF with internal pyramids."""
    output_cog_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Use deflate profile for lossless orthomosaic quality
        dst_profile = cog_profiles.get("deflate")
        dst_profile.update(
            {
                "blockxsize": 512,
                "blockysize": 512,
                "predictor": 2,
            }
        )

        config = {
            "GDAL_NUM_THREADS": "ALL_CPUS",
            "GDAL_TIFF_INTERNAL_MASK": "TRUE",
            "GDAL_TIFF_OVR_BLOCKSIZE": "256",
        }

        cog_translate(
            input_geotiff_path,
            output_cog_path,
            dst_profile,
            config=config,
            overview_resampling=overview_resampling,
            quiet=True,
        )

        return output_cog_path
    except Exception as e:
        logger.warning(
            f"COG generation via rio-cogeo encountered an issue: {e}. Keeping base GeoTIFF."
        )
        return None
