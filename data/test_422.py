import urllib.request
import urllib.error
import json

payload = {
    "dataset_path": "data/raw/sample_drone_survey",
    "dataset_name": "Sample Drone Survey",
    "profile_name": "laptop",
    "preset_name": "balanced"
}
try:
    req = urllib.request.Request(
        "http://127.0.0.1:8088/api/pipeline/run",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        print("Success:", resp.read().decode())
except urllib.error.HTTPError as e:
    print("HTTPError:", e.code, e.read().decode())
