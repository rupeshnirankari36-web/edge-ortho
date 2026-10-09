import json
import time
from pathlib import Path

from edge_ortho.monitor import Phase2MetricsBridge


def test_phase2_events_produce_naman_metrics_artifacts(tmp_path: Path):
    bridge = Phase2MetricsBridge(
        run_id="integration-1",
        dataset_name="synthetic",
        profile="laptop",
        preset="balanced",
        output_dir=tmp_path,
        sample_interval_sec=0.01,
    )
    bridge.start()
    bridge.set_stage("compose")
    time.sleep(0.03)
    bridge.handle_phase2_event({"event": "first_tile", "row": 0, "col": 0, "width": 32, "height": 32})
    bridge.handle_phase2_event({"event": "tile_written", "row": 0, "col": 32, "width": 32, "height": 32})
    time.sleep(0.03)
    bridge.handle_phase2_event({"event": "final_output", "path": "orthomosaic.tif", "bytes": 200})
    summary = bridge.finalize(input_bytes=1000, geotiff_bytes=200, cog_bytes=150)

    assert summary.time_to_first_tile_seconds is not None
    assert summary.output_cog_bytes == 150
    assert (tmp_path / "metrics.json").exists()
    assert (tmp_path / "metrics.csv").exists()
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "resources.png").exists()
    payload = json.loads((tmp_path / "metrics.json").read_text())
    assert payload["run_id"] == "integration-1"
    assert payload["bandwidth_reduction_factor"] > 1
