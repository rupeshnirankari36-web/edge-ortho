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
with urllib.request.urlopen(req) as resp:
    print("Trigger response:", resp.read().decode())

# Poll status
for _ in range(20):
    time.sleep(0.5)
    with urllib.request.urlopen("http://127.0.0.1:8088/api/pipeline/status") as s_resp:
        data = json.loads(s_resp.read().decode())
        print(f"Status: {data['status']}, Stage: {data['current_stage']}, Progress: {data['progress_percent']}%")
        if data['status'] in ('completed', 'error'):
            if data['status'] == 'completed':
                print("Metrics:", data.get('metrics', {}))
                print("Stages:", data.get('stages', {}))
            else:
                print("Error:", data.get('error'))
            break
