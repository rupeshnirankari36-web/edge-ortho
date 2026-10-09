"""Sample dataset acquisition.

The brief requires public datasets so results are reproducible, plus a licence
audit before a dataset is accepted. This module downloads the *small* ones only,
records the licence and source, and never bundles imagery in the repository.

Sources are OpenDroneMap's published example datasets:
https://www.opendronemap.org/odm/datasets/
"""

from __future__ import annotations

import io
import json
import urllib.request
import zipfile
from pathlib import Path

from .config import RAW_DIR, SUPPORTED_EXTENSIONS, ensure_dirs

USER_AGENT = "EdgeOrtho/0.1 (local evaluation; +https://www.opendronemap.org/odm/datasets/)"


SAMPLE_DATASETS: dict[str, dict] = {
    "brighton_beach": {
        "label": "Brighton Beach (18 frames)",
        "description": (
            "Coastal transect flown with a DJI FC300S. Has EXIF GPS plus DJI XMP "
            "relative altitude and gimbal angles. Small, geotagged and quick."
        ),
        "repo": "https://github.com/pierotofy/drone_dataset_brighton_beach",
        "zip": "https://codeload.github.com/pierotofy/drone_dataset_brighton_beach/zip/refs/heads/master",
        "license": "BSD 2-Clause (Copyright (c) 2017, Piero Toffanin)",
        "expected_images": 18,
        "approx_bytes": 62_000_000,
        "gps": True,
        "credit": "Piero Toffanin / OpenDroneMap datasets",
    },
    "mygla": {
        "label": "Mygla (29 frames)",
        "description": (
            "OpenDroneMap's recommended starter set. A larger, more area-like flight "
            "than the beach transect, so it produces a more conventional mosaic."
        ),
        "repo": "https://github.com/merkato/odm_mygla_dataset",
        "zip": "https://codeload.github.com/merkato/odm_mygla_dataset/zip/refs/heads/master",
        "license": "See the repository (OpenDroneMap community dataset)",
        "expected_images": 29,
        "approx_bytes": 150_000_000,
        "gps": True,
        "credit": "OpenDroneMap community",
    },
}

IMAGE_DIR_NAMES = ("images", "img", "photos", "jpeg", "")


def list_samples() -> list[dict]:
    return [
        {"key": key, **{k: v for k, v in meta.items() if k != "zip"}}
        for key, meta in SAMPLE_DATASETS.items()
    ]


def dataset_dir(key: str) -> Path:
    return RAW_DIR / key


def is_installed(key: str) -> bool:
    d = dataset_dir(key)
    if not d.exists():
        return False
    return any(p.suffix.lower() in SUPPORTED_EXTENSIONS for p in d.rglob("*"))


def images_dir(key: str) -> Path | None:
    """Preferred image folder for an installed dataset, mirroring ODM layout."""
    root = dataset_dir(key)
    if not root.exists():
        return None
    for name in IMAGE_DIR_NAMES:
        candidate = root / name if name else root
        if candidate.is_dir():
            files = [p for p in candidate.iterdir() if p.suffix.lower() in SUPPORTED_EXTENSIONS]
            if files:
                return candidate
    best = root
    best_count = 0
    for sub in [root] + [p for p in root.rglob("*") if p.is_dir()]:
        count = sum(1 for p in sub.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS)
        if count > best_count:
            best, best_count = sub, count
    return best if best_count else None


def fetch_sample(key: str, force: bool = False, progress=None) -> dict:
    """Download and unpack a sample dataset into ``data/raw/<key>``.

    Returns a manifest including the licence and source URL so the dataset audit
    is reproducible rather than implied.
    """
    if key not in SAMPLE_DATASETS:
        raise KeyError(f"unknown sample dataset {key!r}; available: {sorted(SAMPLE_DATASETS)}")
    meta = SAMPLE_DATASETS[key]
    ensure_dirs()
    dest = dataset_dir(key)

    if is_installed(key) and not force:
        folder = images_dir(key)
        return {
            "key": key,
            "already_present": True,
            "path": str(folder or dest),
            "images": _count(folder) if folder else 0,
            "license": meta["license"],
            "repo": meta["repo"],
            "message": "dataset already present",
        }

    dest.mkdir(parents=True, exist_ok=True)
    if progress:
        progress(f"downloading {meta['label']} from {meta['repo']}")
    req = urllib.request.Request(meta["zip"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as response:
        payload = response.read()
    if progress:
        progress(f"downloaded {len(payload) / 1e6:.1f} MB; extracting images")

    # GitHub archive zips wrap everything in one top-level directory. Drop just that
    # directory so the upstream layout survives: keeping the original ``images/``
    # folder means discovery sees the flight frames and not a stray DSM or overview
    # raster that happens to share the extension.
    extracted = 0
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = [Path(i.filename).as_posix() for i in zf.infolist() if not i.is_dir()]
        wrapper = _wrapper_dir(names)
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = Path(info.filename)
            if rel.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            parts = rel.parts[1:] if wrapper and len(rel.parts) > 1 else rel.parts
            if not parts:
                continue
            target = dest.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                continue
            with zf.open(info) as fh:
                target.write_bytes(fh.read())
            extracted += 1

    manifest = {
        "key": key,
        "label": meta["label"],
        "path": str(images_dir(key) or dest),
        "images_extracted": extracted,
        "images": _count(images_dir(key) or dest),
        "license": meta["license"],
        "repo": meta["repo"],
        "credit": meta["credit"],
        "note": (
            "Imagery is not redistributed with EdgeOrtho; this fetch copies the upstream "
            "dataset into data/raw/, which is git-ignored."
        ),
    }
    (dest / "DATASET_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if progress:
        progress(f"ready: {manifest['images']} image(s) in {manifest['path']}")
    return manifest


def _wrapper_dir(names: list[str]) -> str | None:
    """The single top-level directory every archive member sits inside, if any."""
    if not names:
        return None
    first = names[0].split("/")[0]
    if all(n.startswith(f"{first}/") for n in names):
        return first
    return None


def _count(folder: Path | None) -> int:
    if not folder or not folder.exists():
        return 0
    return sum(1 for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS)
