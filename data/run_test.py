import urllib.request
import json
import time

payload = {
    "dataset_path": "data/raw/sample_drone_survey",
    "dataset_name": "Sample Drone Survey",
    "profile_name": "laptop",
    "preset_name": "balanced"
}

req = urllib.request.Request(
    "http://127.0.0.1:8088/api/pipeline/run",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)

try:
    with urllib.request.urlopen(req, timeout=5) as resp:
        print("Response:", resp.status, resp.read().decode())
except Exception as e:
    print("Request exception:", e)
    if hasattr(e, "read"):
        print("Details:", e.read().decode())
