"""File discovery for the ingestion stage."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import SUPPORTED_EXTENSIONS


@dataclass
class DiscoveryResult:
    root: Path | None
    images: list[Path] = field(default_factory=list)
    skipped_unsupported: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.images)

    def to_dict(self) -> dict:
        return {
            "root": str(self.root) if self.root else None,
            "image_count": self.count,
            "images": [str(p) for p in self.images],
            "skipped_unsupported": self.skipped_unsupported[:200],
            "skipped_unsupported_count": len(self.skipped_unsupported),
            "missing": self.missing,
        }


def discover_images(source: str | Path, recursive: bool = True) -> DiscoveryResult:
    """Find supported image files under ``source``.

    ``source`` may be a directory or a single image file. Unsupported files are
    recorded (not silently dropped) so the validation report can explain them.
    """
    path = Path(source)
    result = DiscoveryResult(root=path if path.is_dir() else path.parent)

    if not path.exists():
        result.missing.append(str(path))
        return result

    if path.is_file():
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            result.images.append(path)
        else:
            result.skipped_unsupported.append(path.name)
        return result

    walker = path.rglob("*") if recursive else path.glob("*")
    for entry in sorted(walker):
        if not entry.is_file():
            continue
        if entry.name.startswith("."):
            continue
        if entry.suffix.lower() in SUPPORTED_EXTENSIONS:
            result.images.append(entry)
        elif entry.suffix.lower() in {".png", ".bmp", ".gif", ".webp", ".mp4", ".mov", ".dng"}:
            # Recognised but outside the supported ingestion contract.
            result.skipped_unsupported.append(entry.name)
    return result
