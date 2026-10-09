import urllib.request
import mimetypes

boundary = '----BoundaryTest12345678'
lines = []

def add_field(name, value):
    lines.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode('utf-8'))

def add_file(field_name, file_path, filename):
    lines.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\nContent-Type: application/zip\r\n\r\n'.encode('utf-8'))
    with open(file_path, 'rb') as f:
        lines.append(f.read())
    lines.append(b'\r\n')

add_field('name', 'test_upload_survey')
add_file('zip_file', 'data/sample_drone_mission.zip', 'sample_drone_mission.zip')
lines.append(f'--{boundary}--\r\n'.encode('utf-8'))

body = b''.join(lines)
req = urllib.request.Request(
    'http://127.0.0.1:8088/api/upload-dataset',
    data=body,
    headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}
)
with urllib.request.urlopen(req) as resp:
    print('Upload response:', resp.status, resp.read().decode())
