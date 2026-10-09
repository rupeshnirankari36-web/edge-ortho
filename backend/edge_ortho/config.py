"""Runtime configuration, storage paths and named pipeline presets."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent  # edge-ortho/

DATA_DIR = Path(os.environ.get("EDGEORTHO_DATA_DIR", PROJECT_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
UPLOAD_DIR = DATA_DIR / "uploads"
META_DIR = DATA_DIR / "meta"
OUTPUT_DIR = Path(os.environ.get("EDGEORTHO_OUTPUT_DIR", PROJECT_ROOT / "outputs"))
DB_PATH = Path(os.environ.get("EDGEORTHO_DB", DATA_DIR / "edgeortho.sqlite3"))

DEFAULT_MATCHING_MEGAPIXELS = 0.6  # brief: "approximately 0.6 MP matching copies"
DEFAULT_TILE_SIZE = 2048  # brief: "approximately 2048 x 2048 tiles"

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".tif", ".tiff"}


@dataclass
class PipelineSettings:
    """Everything a user can change about a run."""

    profile: str = "laptop"
    preset: str = "balanced"

    # -- matching ---------------------------------------------------------
    matching_megapixels: float = DEFAULT_MATCHING_MEGAPIXELS
    feature_detector: str = "orb"  # orb | akaze
    orb_features: int = 3000
    ratio_threshold: float = 0.75
    ransac_threshold_px: float = 3.0
    ransac_confidence: float = 0.999
    ransac_max_iters: int = 5000
    min_matches: int = 18
    min_inliers: int = 12
    max_reprojection_error_px: float = 3.0

    # -- planning ---------------------------------------------------------
    neighbour_radius_factor: float = 0.85  # x footprint diagonal
    neighbour_max_links: int = 12
    min_estimated_overlap: float = 0.15

    # -- alignment --------------------------------------------------------
    alignment_model: str = "affine"  # "affine" | "homography" | "both"
    global_max_iterations: int = 60
    gps_prior_weight: float = 0.05  # weak GPS prior (brief: "weak GPS prior")

    # -- composition ------------------------------------------------------
    tile_size: int = DEFAULT_TILE_SIZE
    # Keep the EXIF-derived/native GSD by default. 60 MP was too aggressive for
    # ordinary drone sets and silently coarsened the final raster.
    max_output_megapixels: float = 200.0
    decode_cache_size: int = 2
    # None means decode at source resolution. Set this explicitly on constrained
    # hardware when bounded memory is more important than pixel fidelity.
    max_decode_side: int | None = None
    seam_blend_px: int = 48
    exposure_compensation: bool = True
    output_gsd_m: float | None = None  # None == use estimated native GSD (capped)

    # -- outputs ----------------------------------------------------------
    min_valid_frames: int = 4

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PipelineSettings:
        data = data or {}
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def replace(self, **changes: Any) -> PipelineSettings:
        return PipelineSettings.from_dict({**self.to_dict(), **changes})


@dataclass
class Preset:
    """A named bundle of settings tuned for a workload."""

    name: str
    label: str
    description: str
    settings: dict[str, Any] = field(default_factory=dict)


PRESETS: dict[str, Preset] = {
    "smoke": Preset(
        name="smoke",
        label="Smoke test",
        description=(
            "Smallest, fastest configuration for a first look at a dataset. "
            "Coarser output; intended only to confirm the pipeline runs end to end."
        ),
        settings={
            "orb_features": 1500,
            "min_matches": 12,
            "min_inliers": 8,
            "max_output_megapixels": 12.0,
            "max_reprojection_error_px": 4.0,
        },
    ),
    "balanced": Preset(
        name="balanced",
        label="Balanced (default)",
        description=(
            "Default field configuration: 0.6 MP matching copies, ORB, affinity "
            "alignment with a weak GPS prior and 2048 px output tiles."
        ),
        settings={},
    ),
    "quality": Preset(
        name="quality",
        label="Quality",
        description=(
            "More features, tighter RANSAC and a higher output pixel cap. "
            "Slower and more memory-hungry; use on a laptop profile."
        ),
        settings={
            "orb_features": 6000,
            "ratio_threshold": 0.72,
            "ransac_threshold_px": 2.0,
            "min_matches": 30,
            "min_inliers": 20,
            "max_output_megapixels": 200.0,
        },
    ),
}


def resolve_settings(
    profile: str | None = None,
    preset: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> PipelineSettings:
    """Preset baseline -> explicit overrides. Explicit user values always win."""
    settings = PipelineSettings()
    if preset:
        if preset not in PRESETS:
            raise KeyError(f"unknown preset {preset!r} (have {sorted(PRESETS)})")
        settings = settings.replace(preset=preset, **PRESETS[preset].settings)
    if profile:
        settings = settings.replace(profile=profile)
    if overrides:
        settings = settings.replace(**overrides)
    return settings


def ensure_dirs() -> None:
    for p in (DATA_DIR, RAW_DIR, UPLOAD_DIR, META_DIR, OUTPUT_DIR):
        p.mkdir(parents=True, exist_ok=True)


def run_output_dir(run_id: str) -> Path:
    p = OUTPUT_DIR / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_meta_path(run_id: str) -> Path:
    d = META_DIR / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d
