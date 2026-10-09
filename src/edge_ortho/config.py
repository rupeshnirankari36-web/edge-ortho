"""Configuration management and profile/preset loaders."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ProfileConfig:
    name: str = "pi-class"
    description: str = "Standard Raspberry Pi 4/5 (4GB) edge profile"
    max_cpus: int | None = 4
    max_ram_mb: int | None = 4096
    max_swap_mb: int | None = 0
    matching_image_max_dim: int = 1000
    feature_limit: int = 1500
    tile_size: int = 2048
    max_cached_frames: int = 4
    matcher: str = "akaze"
    transform_model: str = "affine"
    chunk_size: int = 8
    multiband_blending: bool = False


@dataclass
class PipelineConfig:
    # Execution metadata
    run_id: str = "default_run"
    profile_name: str = "pi-class"
    preset_name: str = "balanced"

    # Matching and Features
    matcher: str = "akaze"  # "orb" | "akaze" | "sift"
    feature_limit: int = 1500
    matching_image_max_dim: int = 1000
    ratio_test_threshold: float = 0.75

    # Neighbor Graph
    k_neighbors: int = 6
    max_neighbor_distance_m: float = 80.0

    # Geometric Alignment
    transform_model: str = "affine"  # "similarity" | "affine" | "homography"
    ransac_thresh_px: float = 4.0
    min_inliers: int = 15
    gps_prior_weight: float = 0.05

    # Composition & Blending
    tile_size: int = 2048
    blend_mode: str = "feather"  # "feather" | "multiband" | "average"
    feather_radius_px: int = 25
    exposure_compensation: bool = True
    output_resolution_factor: float = 1.0  # 1.0 = native GSD
    multiband_blending: bool = False

    # Export formats
    generate_cog: bool = True
    generate_tiles: bool = True
    tile_min_zoom: int | None = None
    tile_max_zoom: int | None = None

    # Hardware bounds
    max_cpus: int | None = 4
    max_ram_mb: int | None = 4096
    max_cached_frames: int = 4

    extra: dict[str, Any] = field(default_factory=dict)


def load_yaml(file_path: Path) -> dict[str, Any]:
    if not file_path.exists():
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_pipeline_config(
    profile_name: str = "pi-class",
    preset_name: str = "balanced",
    overrides: dict[str, Any] | None = None,
    profiles_dir: Path | None = None,
    configs_dir: Path | None = None,
) -> PipelineConfig:
    root = Path(__file__).resolve().parent.parent.parent
    if profiles_dir is None:
        profiles_dir = root / "profiles"
    if configs_dir is None:
        configs_dir = root / "configs"

    profile_file = profiles_dir / f"{profile_name.replace('-', '_')}.yaml"
    if not profile_file.exists():
        profile_file = profiles_dir / f"{profile_name}.yaml"

    preset_file = configs_dir / f"{preset_name}.yaml"

    profile_data = load_yaml(profile_file)
    preset_data = load_yaml(preset_file)

    # Base config from dataclass defaults
    cfg_kwargs: dict[str, Any] = {
        "profile_name": profile_name,
        "preset_name": preset_name,
    }

    # Overlay profile values
    for k, v in profile_data.items():
        if hasattr(PipelineConfig, k):
            cfg_kwargs[k] = v

    # Overlay preset values
    for k, v in preset_data.items():
        if hasattr(PipelineConfig, k):
            cfg_kwargs[k] = v

    # User command line overrides have highest precedence
    if overrides:
        for k, v in overrides.items():
            if v is not None and hasattr(PipelineConfig, k):
                cfg_kwargs[k] = v

    return PipelineConfig(**cfg_kwargs)
