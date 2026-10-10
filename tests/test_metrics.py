"""Measurement correctness: the numbers the product reports.

The brief is explicit that measurements must be real and that unavailable values
must be marked as unavailable rather than filled in. These tests pin the arithmetic
(bandwidth, throughput, reduction) and the behaviour of the sampling, the profile
limits and the memory guard.
"""

from __future__ import annotations

import pytest

from edge_ortho import config
from edge_ortho.contracts import (
    BANDWIDTH_TEST_MBPS,
    bandwidth_table,
    human_bytes,
    human_duration,
    transfer_seconds,
)
from edge_ortho.monitor.resources import MemoryCeilingExceeded, MemoryGuard, ResourceSampler
from edge_ortho.profiles import PROFILES, ResourceLimiter, get_profile


# --------------------------------------------------------------------------
# bandwidth
# --------------------------------------------------------------------------

def test_transfer_seconds_uses_the_formula_from_the_brief():
    assert transfer_seconds(0, 1_000_000) == 0
    assert transfer_seconds(1_000_000, 1_000_000) == pytest.approx(8.0)
    # 65 MB at 1 Mbps = 65e6 * 8 / 1e6 = 520 s
    assert transfer_seconds(65_000_000, 1_000_000) == pytest.approx(520.0)
    assert transfer_seconds(65_000_000, 20_000_000) == pytest.approx(26.0)


def test_transfer_seconds_rejects_a_non_positive_link():
    with pytest.raises(ValueError):
        transfer_seconds(1000, 0)


def test_bandwidth_table_reports_the_three_documented_rates():
    table = bandwidth_table(65_000_000, 168_000_000, 11_000_000)
    assert list(table["scenarios"]) == [str(r) for r in BANDWIDTH_TEST_MBPS]
    for mbps in BANDWIDTH_TEST_MBPS:
        row = table["scenarios"][str(mbps)]
        bps = mbps * 1_000_000
        assert row["input_seconds"] == pytest.approx(65_000_000 * 8 / bps)
        assert row["output_seconds"] == pytest.approx(168_000_000 * 8 / bps)
        assert row["web_seconds"] == pytest.approx(11_000_000 * 8 / bps)


def test_bandwidth_table_states_a_negative_difference_instead_of_a_saving():
    table = bandwidth_table(65_000_000, 168_000_000, 11_000_000)
    row = table["scenarios"]["1"]
    # The products are bigger than the input: the "saved" figure must be negative.
    assert row["saved_seconds"] is not None and row["saved_seconds"] < 0
    assert row["saved_human"].startswith("-")
    # ...while the web deliverables really are smaller.
    assert row["web_saved_seconds"] > 0
    assert not row["web_saved_human"].startswith("-")


def test_bandwidth_reduction_factors_are_measured_not_assumed():
    table = bandwidth_table(65_000_000, 168_000_000, 11_000_000)
    assert table["reduction_factor"] == pytest.approx(65 / 168, rel=1e-6)
    assert table["web_reduction_factor"] == pytest.approx(65 / 11, rel=1e-6)
    assert table["formula"] == "transfer_seconds = bytes * 8 / bits_per_second"


def test_bandwidth_table_marks_missing_bytes_as_unavailable():
    table = bandwidth_table(None, None, None)
    for mbps in BANDWIDTH_TEST_MBPS:
        row = table["scenarios"][str(mbps)]
        assert row["input_seconds"] is None
        assert row["output_seconds"] is None
        assert row["web_seconds"] is None
        assert row["saved_seconds"] is None
    assert table["reduction_factor"] is None
    assert table["web_reduction_factor"] is None


def test_zero_output_bytes_does_not_divide_by_zero():
    table = bandwidth_table(1_000, 0, 0)
    assert table["reduction_factor"] is None
    assert table["web_reduction_factor"] is None


def test_human_duration_formats_each_magnitude():
    assert human_duration(None) is None
    assert human_duration(0.25) == "250 ms"
    assert human_duration(9.4) == "9.4 s"
    assert human_duration(600) == "10m 0s"
    assert human_duration(3_600 + 180) == "1h 3m"
    assert human_duration(-600) == "-10m 0s"


def test_human_bytes_is_binary_and_marks_unknown_as_none():
    assert human_bytes(None) is None
    assert human_bytes(512) == "512 B"
    assert human_bytes(1024) == "1.0 KB"
    assert human_bytes(65_000_000) == "62.0 MB"


# --------------------------------------------------------------------------
# profiles and limits
# --------------------------------------------------------------------------

def test_the_four_brief_profiles_exist_with_their_limits():
    assert set(PROFILES) >= {"laptop", "pi-lite", "pi-class", "jetson-class"}
    laptop = get_profile("laptop")
    assert laptop.cpu_cores is None and laptop.ram_limit_mb is None
    lite = get_profile("pi-lite")
    assert lite.cpu_cores == 2 and lite.ram_limit_mb == 2048
    klass = get_profile("pi-class")
    assert klass.cpu_cores == 4 and klass.ram_limit_mb == 4096
    jetson = get_profile("jetson-class")
    assert jetson.cpu_cores == 6


def test_unknown_profile_is_rejected():
    with pytest.raises(KeyError):
        get_profile("gaming-pc")


def test_laptop_profile_applies_no_constraints():
    limiter = ResourceLimiter(get_profile("laptop"))
    enforcement = limiter.apply()
    try:
        assert enforcement["cpu_affinity_requested"] is None
        assert enforcement["ram_limit_mb"] is None
        assert enforcement["notes"]
    finally:
        limiter.restore()


def test_constrained_profile_reports_what_it_actually_applied(capfd):
    limiter = ResourceLimiter(get_profile("pi-class"))
    enforcement = limiter.apply()
    try:
        assert enforcement["profile"] == "pi-class"
        assert enforcement["ram_limit_mb"] == 4096
        # Affinity may legitimately fail on some hosts; the report must say which.
        assert "cpu_affinity_applied" in enforcement
        assert isinstance(enforcement["cpu_affinity_applied"], bool)
        if enforcement["cpu_affinity_applied"]:
            assert enforcement["cpu_affinity_actual"]
    finally:
        limiter.restore()


def test_enforcement_notes_are_explicit_about_emulation():
    enforcement = ResourceLimiter(get_profile("pi-lite")).apply()
    text = " ".join(enforcement["notes"]).lower()
    assert "soft" in text or "ceiling" in text
    assert "raspberry" in text or "physical" in text


# --------------------------------------------------------------------------
# sampling and the memory guard
# --------------------------------------------------------------------------

def test_sampler_records_a_real_peak_and_runtime():
    sampler = ResourceSampler(interval_s=0.02)
    sampler.start()
    # Allocate something measurable so the peak is not just the baseline.
    ballast = bytearray(24 * 1024 * 1024)
    for byte in range(0, len(ballast), 4 * 1024 * 1024):
        ballast[byte] = 1
    sampler._sample_once()
    sampler.stop()
    summary = sampler.summary()
    assert summary["baseline_rss_mb"] is not None and summary["baseline_rss_mb"] > 0
    assert summary["peak_rss_mb"] is not None
    assert summary["peak_rss_mb"] > summary["baseline_rss_mb"]
    assert summary["elapsed_s"] > 0
    assert summary["rss_samples"] >= 1
    assert summary["peak_rss_delta_mb"] is not None
    assert len(ballast) == 24 * 1024 * 1024


def test_sampler_reports_cpu_and_disk_or_says_why_not():
    sampler = ResourceSampler(interval_s=0.05)
    sampler.start()
    sampler._sample_once()
    sampler.stop()
    disk = sampler.disk_summary()
    if disk.get("available"):
        assert disk["read_bytes"] >= 0 and disk["write_bytes"] >= 0
        assert "differenced" in disk["scope"]
    else:
        assert disk.get("reason")
    cpu = sampler.cpu_summary()
    assert cpu["available"] is True
    assert cpu["cores_available_to_process"] >= 1
    assert cpu["peak_percent_of_machine"] <= cpu["peak_percent_of_one_core"] + 1e-6


def test_memory_guard_is_inert_without_a_limit():
    sampler = ResourceSampler()
    guard = MemoryGuard(None, sampler, "laptop")
    guard.check()  # must not raise
    assert guard.exceeded is False


def test_memory_guard_stops_a_run_that_exceeds_the_ceiling():
    sampler = ResourceSampler()
    sampler.start()
    installer = bytearray(40 * 1024 * 1024)
    sampler._sample_once()
    guard = MemoryGuard(1, sampler, "pi-lite")  # 1 MB ceiling, certainly exceeded
    with pytest.raises(MemoryCeilingExceeded):
        guard.check()
    assert guard.exceeded is True
    assert guard.peak_seen_mb is not None
    sampler.stop()
    assert len(installer) == 40 * 1024 * 1024


def test_memory_guard_message_names_the_profile_and_a_way_out():
    sampler = ResourceSampler()
    guard = MemoryGuard(1, sampler, "pi-lite")
    with pytest.raises(MemoryCeilingExceeded) as excinfo:
        guard.check()
    message = str(excinfo.value)
    assert "pi-lite" in message
    assert "profile" in message and "MB" in message


# --------------------------------------------------------------------------
# settings contract
# --------------------------------------------------------------------------

def test_settings_round_trip_and_ignore_unknown_keys():
    settings = config.PipelineSettings(profile="pi-class", tile_size=1024, matching_megapixels=0.5)
    restored = config.PipelineSettings.from_dict(
        {**settings.to_dict(), "this_key_does_not_exist": 42}
    )
    assert restored == settings
    assert restored.tile_size == 1024


def test_every_preset_key_is_a_real_setting():
    known = set(config.PipelineSettings().to_dict())
    for name, preset in config.PRESETS.items():
        unknown = set(preset.settings) - known
        assert not unknown, f"preset {name} sets unknown fields: {sorted(unknown)}"


def test_defaults_match_the_brief():
    defaults = config.PipelineSettings()
    assert 0.5 <= defaults.matching_megapixels <= 0.7  # "approximately 0.6 MP"
    assert defaults.tile_size in {1024, 2048, 4096}  # "approximately 2048 px tiles"
    assert defaults.alignment_model == "affine"
    assert defaults.gps_prior_weight > 0  # weak GPS prior, not a hard constraint
