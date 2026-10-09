"""Core data structures for the ingestion pipeline stage."""

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class FrameRecord:
    """Represents an ingested aerial image frame with spatial and sensor metadata."""

    frame_id: str
    path: Path
    lat: float
    lon: float
    altitude: float  # Relative or MSL altitude in meters
    yaw: float | None = None  # Heading degrees (0..360, 0=North)
    pitch: float | None = None  # Gimbal pitch (-90=nadir)
    focal_length: float | None = None  # Sensor focal length (mm)
    focal_length_35mm: float | None = None
    width: int = 0
    height: int = 0
    timestamp: str | None = None
    camera_model: str | None = None

    # Derived planning fields
    gsd_m: float | None = None  # Ground Sampling Distance (m/px)
    utm_easting: float | None = None
    utm_northing: float | None = None
    utm_epsg: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["path"] = str(self.path)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FrameRecord":
        copied = dict(data)
        copied["path"] = Path(copied["path"])
        return cls(**copied)


@dataclass
class IngestionReport:
    total_found: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    records: list[FrameRecord] = None
    rejections: list[dict[str, str]] = None  # [{"file": path, "reason": msg}]

    def __post_init__(self):
        if self.records is None:
            self.records = []
        if self.rejections is None:
            self.rejections = []
