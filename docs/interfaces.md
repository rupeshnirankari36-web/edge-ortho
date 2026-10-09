# Edge-Ortho Integration Contracts & Schemas

This document defines the strictly enforced data transfer objects (DTOs) and interchange formats between pipeline stages. Each team member owns specific components and interfaces through these dataclasses/schemas.

---

## 1. FrameRecord (Ingest -> Plan / Match)
**Owner:** Abhyuday (`src/edge_ortho/ingest/`)

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class FrameRecord:
    frame_id: str
    path: Path
    lat: float
    lon: float
    altitude: float  # Absolute or relative MSL in meters
    yaw: Optional[float]  # Degrees clockwise from North (0-360)
    focal_length: Optional[float]  # In mm (or 35mm equivalent if normalized)
    width: int  # Native pixel width
    height: int  # Native pixel height
    timestamp: Optional[str] = None
    camera_model: Optional[str] = None
    gsd_m: Optional[float] = None  # Ground Sampling Distance in meters/pixel
    utm_easting: Optional[float] = None
    utm_northing: Optional[float] = None
    utm_epsg: Optional[int] = None
```

---

## 2. Neighbor Pairs (Plan -> Match)
**Owner:** Abhyuday (`src/edge_ortho/plan/`)

```python
@dataclass
class NeighborPair:
    source_id: str
    target_id: str
    distance_meters: float
```

A spatial KD-Tree based on projected UTM coordinates limits feature matching to physically adjacent candidate pairs (e.g. $k$-nearest neighbors or within radius $R$), avoiding $O(N^2)$ all-pairs matching.

---

## 3. PairTransform (Match -> Align)
**Owner:** Abhyuday (`src/edge_ortho/features/` & `src/edge_ortho/align/`)

```python
from enum import Enum
import numpy as np


class TransformModel(str, Enum):
    SIMILARITY = "similarity"
    AFFINE = "affine"
    HOMOGRAPHY = "homography"


@dataclass
class PairTransform:
    source_id: str
    target_id: str
    model_type: TransformModel
    matrix: np.ndarray  # 3x3 homogeneous matrix mapping source -> target
    num_matches: int
    num_inliers: int
    inlier_ratio: float
    reprojection_error: float
    status: str  # "success" | "low_inliers" | "failed"
```

---

## 4. GlobalPose (Align -> Compose)
**Owner:** Abhyuday (`src/edge_ortho/align/global_solve.py`)

```python
@dataclass
class GlobalPose:
    frame_id: str
    # Projected world coordinates (UTM meters or canvas coordinate space)
    world_x: float
    world_y: float
    scale_x: float
    scale_y: float
    rotation_rad: float
    # Global 3x3 affine/homography transform matrix mapping frame native pixels to world/canvas pixels
    h_native_to_canvas: np.ndarray
    confidence: float
```

---

## 5. MosaicMetadata (Compose / Geo -> Web Viewers)
**Owner:** Rupesh (`src/edge_ortho/geo/`)

```python
@dataclass
class MosaicMetadata:
    crs_epsg: int
    transform_affine: list[float]  # 6-element affine transform tuple [a, b, c, d, e, f]
    bounds_utm: tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)
    bounds_wgs84: tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat)
    width_px: int
    height_px: int
    pixel_size_m: float
    nodata_value: int
    geotiff_path: str
    cog_path: Optional[str]
    tiles_dir: Optional[str]
```

---

## 6. MetricEvent (Monitor -> Report)
**Owner:** Naman (`src/edge_ortho/monitor/`)

```python
@dataclass
class MetricEvent:
    run_id: str
    stage: str
    timestamp: float
    elapsed_seconds: float
    cpu_percent: float
    rss_ram_mb: float
    disk_read_mb: float
    disk_write_mb: float
    status: str
```
