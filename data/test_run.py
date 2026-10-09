import urllib.request
import urllib.parse
import json
import time

data = urllib.parse.urlencode({
    'dataset_path': 'data/raw/sample_drone_survey',
    'dataset_name': 'Sample Drone Survey',
    'profile_name': 'laptop',
    'preset_name': 'balanced'
}).encode('utf-8')

req = urllib.request.Request('http://127.0.0.1:8088/api/pipeline/run', data=data)
with urllib.request.urlopen(req) as resp:
    print('Run trigger response:', resp.read().decode())

for i in range(15):
    time.sleep(1)
    status_req = urllib.request.Request('http://127.0.0.1:8088/api/pipeline/status')
    with urllib.request.urlopen(status_req) as s_resp:
        st = json.loads(s_resp.read().decode())
        print(f"[{i}s] status={st['status']} stage={st['current_stage']} progress={st['progress_percent']}% elapsed={st['elapsed_seconds']}s")
        if st['status'] in ('completed', 'error'):
            if st['status'] == 'completed':
                print('Success metrics:', st['metrics'])
            else:
                print('Error:', st['error'])
            break
