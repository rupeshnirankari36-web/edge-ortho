"""Edge hardware profiles from the GEOAI 01 brief.

    | profile      | CPU limit | RAM limit | meaning                        |
    |--------------|-----------|-----------|--------------------------------|
    | pi-lite      | 2 cores   | 2 GB      | very constrained edge profile  |
    | pi-class     | 4 cores   | 4 GB      | main acceptance profile        |
    | jetson-class | 6 cores   | 8 GB      | Jetson-class CPU-only emulation|
    | laptop       | host      | host      | baseline profile               |

Honesty rules implemented here (not just documented):

* A profile is a *configured/constrained* execution environment, never a
  claim about physical Raspberry Pi or Jetson timing.
* CPU cores are enforced for real via process CPU affinity when the platform
  supports it. Whether it was actually applied is reported per run.
* The RAM limit is enforced as a *soft ceiling*: the run is aborted with a
  clear error when process RSS crosses the limit. It is not a hard cgroup.
* Nothing here is reported as "measured on a Raspberry Pi".
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict, dataclass

try:  # psutil is a hard requirement, but keep import guard for docs/tests
    import psutil
except Exception:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

MB = 1024 * 1024


@dataclass(frozen=True)
class HardwareProfile:
    name: str
    label: str
    cpu_cores: int | None  # None == use all host cores
    ram_limit_mb: int | None  # None == no soft ceiling
    description: str
    acceptance: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


PROFILES: dict[str, HardwareProfile] = {
    "laptop": HardwareProfile(
        name="laptop",
        label="Laptop (baseline)",
        cpu_cores=None,
        ram_limit_mb=None,
        description=(
            "Host defaults. No CPU affinity and no RAM ceiling are applied; "
            "this is the reference environment for the other profiles."
        ),
        acceptance=False,
    ),
    "pi-lite": HardwareProfile(
        name="pi-lite",
        label="Pi-lite",
        cpu_cores=2,
        ram_limit_mb=2048,
        description=(
            "Very constrained edge profile: 2 cores and a 2 GB soft RAM ceiling. "
            "Configured limits only - not a physical device measurement."
        ),
        acceptance=False,
    ),
    "pi-class": HardwareProfile(
        name="pi-class",
        label="Pi-class",
        cpu_cores=4,
        ram_limit_mb=4096,
        description=(
            "Main acceptance profile: 4 cores and a 4 GB soft RAM ceiling. "
            "Configured limits only - not a physical device measurement."
        ),
        acceptance=True,
    ),
    "jetson-class": HardwareProfile(
        name="jetson-class",
        label="Jetson-class",
        cpu_cores=6,
        ram_limit_mb=8192,
        description=(
            "Jetson-class CPU-only emulation: 6 cores and an 8 GB soft RAM ceiling. "
            "Configured limits only - not a physical device measurement."
        ),
        acceptance=False,
    ),
}

DEFAULT_PROFILE = "laptop"


def host_cores() -> int:
    if psutil is not None:
        return psutil.cpu_count(logical=True) or 1
    import os

    return os.cpu_count() or 1


def get_profile(name: str | None) -> HardwareProfile:
    if not name:
        return PROFILES[DEFAULT_PROFILE]
    key = name.strip().lower().replace("_", "-")
    if key not in PROFILES:
        raise KeyError(f"unknown hardware profile: {name!r} (have {sorted(PROFILES)})")
    return PROFILES[key]


class ResourceLimiter:
    """Applies and reports the constraints for a profile.

    `apply()` returns a machine-readable description of which constraints were
    really enforced so the UI can distinguish "configured" from "measured".
    """

    def __init__(self, profile: HardwareProfile):
        self.profile = profile
        self._original_affinity: list[int] | None = None
        self.enforcement: dict = {
            "profile": profile.name,
            "cpu_affinity_applied": False,
            "cpu_affinity_requested": profile.cpu_cores,
            "ram_ceiling_enforced": False,
            "ram_limit_mb": profile.ram_limit_mb,
            "notes": [],
        }

    # -- CPU ---------------------------------------------------------------
    def apply(self) -> dict:
        prof = self.profile
        hc = host_cores()
        if prof.cpu_cores is None:
            self.enforcement["notes"].append(
                "No CPU limit requested for this profile; all host cores are available."
            )
        elif prof.cpu_cores > hc:
            self.enforcement["notes"].append(
                f"Requested {prof.cpu_cores} cores but host only has {hc}; "
                "no affinity restriction applied."
            )
        else:
            try:
                if psutil is not None:
                    proc = psutil.Process()
                    self._original_affinity = proc.cpu_affinity()
                    proc.cpu_affinity(list(range(prof.cpu_cores)))
                    self.enforcement["cpu_affinity_applied"] = True
                    self.enforcement["cpu_affinity_actual"] = proc.cpu_affinity()
            except Exception as exc:  # pragma: no cover - platform dependent
                self.enforcement["notes"].append(
                    f"CPU affinity could not be applied on this platform: {exc}"
                )

        if prof.ram_limit_mb is not None:
            self.enforcement["ram_ceiling_enforced"] = True
            self.enforcement["notes"].append(
                "RAM limit is a soft ceiling: the run aborts if process RSS exceeds it. "
                "It does not emulate physical Raspberry Pi or Jetson memory bandwidth."
            )
        else:
            self.enforcement["notes"].append("No RAM ceiling requested for this profile.")
        return self.enforcement

    # -- teardown ----------------------------------------------------------
    def restore(self) -> None:
        if self._original_affinity and psutil is not None:
            with suppress(Exception):
                psutil.Process().cpu_affinity(self._original_affinity)


class MemoryCeilingExceeded(RuntimeError):
    """Raised when a constrained profile's RAM ceiling is crossed."""


def check_memory_ceiling(profile: HardwareProfile, rss_bytes: int) -> None:
    if profile.ram_limit_mb is None:
        return
    if rss_bytes > profile.ram_limit_mb * MB:
        raise MemoryCeilingExceeded(
            f"profile {profile.name!r} RAM ceiling of {profile.ram_limit_mb} MB exceeded "
            f"(process RSS {rss_bytes / MB:.0f} MB). Re-run with a higher-memory profile or "
            "increase the output pixel cap to reduce buffering."
        )
