import csv
from pathlib import Path

from edge_ortho.dataset_verifier import verify_metadata_csv, write_verification_report


def test_dataset_verification_counts_actual_metadata(tmp_path: Path):
    path = tmp_path / "meta.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["SourceFile", "GPSLatitude", "GPSLongitude", "GPSAltitude", "Model"])
        writer.writeheader()
        writer.writerow({"SourceFile": "a.JPG", "GPSLatitude": "19.1", "GPSLongitude": "73.1", "GPSAltitude": "100", "Model": "A"})
        writer.writerow({"SourceFile": "b.JPG", "GPSLatitude": "", "GPSLongitude": "", "GPSAltitude": "", "Model": "A"})
    report = verify_metadata_csv(path, dataset="fixture", source_url="https://example.invalid/source")
    assert report["total_files"] == 2
    assert report["gps_files"] == 1
    assert report["files_without_gps"] == 1
    assert report["status"] == "accepted_with_limitations"
    output = write_verification_report(report, tmp_path / "report.json")
    assert output.exists()
