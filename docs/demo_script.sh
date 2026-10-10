#!/usr/bin/env bash
# EdgeOrtho evaluation demo.
#
# Prerequisites:
#   - Python 3.11/3.12 with the backend dependencies installed
#   - A local checkout of this repo with a sample dataset available or
#     connected to the internet for the first-run download
#
# This script exercises the product the way a user does: through the local API.
# It is intentionally slower than the test suite because it runs the actual
# pipeline on imagery, so run it only when you want a real end-to-end result.

set -euo pipefail

BASE="http://127.0.0.1:8077"
PROJ_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$PROJ_ROOT/data"
RAW_DIR="$DATA_DIR/raw"
OUT_DIR="$PROJ_ROOT/outputs"
META_DIR="$DATA_DIR/meta"
LOG="$PROJ_ROOT/_probe/demo_run.log"

# ----------------------------------------------------------------------
# 0. sanity: start the backend if it is not running (development only)
# ----------------------------------------------------------------------
if ! curl -s --max-time 4 "$BASE/api/health" > /dev/null 2>&1; then
    echo ">>> starting the backend from $PROJ_ROOT"
    cd "$PROJ_ROOT/backend"
    nohup python -m edge_ortho.cli serve --host 127.0.0.1 --port 8077 > "$LOG" 2>&1 &
    sleep 8
    if ! curl -s --max-time 4 "$BASE/api/health" > /dev/null 2>&1; then
        echo "!! backend did not start; aborting"
        exit 2
    fi
    cd "$PROJ_ROOT"
fi

cd "$PROJ_ROOT"

# ----------------------------------------------------------------------
# 1. fetch the sample dataset (only if not already present)
# ----------------------------------------------------------------------
DATASET="brighton_beach"
DATASET_PATH="$RAW_DIR/$DATASET"
DATASET_MANIFEST="$DATASET_PATH/DATASET_MANIFEST.json"

if [ ! -f "$DATASET_MANIFEST" ]; then
    echo ">>> fetching $DATASET sample dataset (first-run download)"
    curl -s --max-time 300 -X POST "$BASE/api/samples/$DATASET/fetch" \
        | python -c "import json,sys; d=json.load(sys.stdin); print(d['key'], d['images'], d['license'][:40])"
fi

# ----------------------------------------------------------------------
# 2. inspect the dataset
# ----------------------------------------------------------------------
SOURCE_FOLDER="$DATASET_PATH/images"
if [ ! -d "$SOURCE_FOLDER" ]; then
    # some dataset layouts put images at the root; fall back
    SOURCE_FOLDER="$DATASET_PATH/../images"
    if [ ! -d "$SOURCE_FOLDER" ]; then
        SOURCE_FOLDER="$DATASET_PATH"
    fi
fi

echo ">>> inspecting $SOURCE_FOLDER"
inspect_resp=$(curl -s --max-time 120 -X POST "$BASE/api/sources/inspect" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg p "$SOURCE_FOLDER" '{path: $p}')")

python - "$inspect_resp" <<'PY'
import json, sys
d = json.load(sys.stdin)
s = d["summary"]
print(
    f"   {s['frames_accepted']} accepted / {s['frames_rejected']} rejected "
    f"of {d['discovery']['image_count']} discovered "
    f"({s['total_bytes']/1e6:.1f} MB)"
)
print(f"   GPS={s['gps_available']} altitude={s['altitude_available']} yaw={s['yaw_available']} "
      f"GSD={s['gsd_m']}")
for w in d.get("dataset_warnings", []):
    print(f"   ! {w['text']}: {w['detail']}")
if not d.get("suitable"):
    print(f"   x unsuitable: {d.get('unsuitability_reasons')}")
    sys.exit(2)
PY

echo "$(cat _probe/demo_run.log 2>/dev/null || true)" | tail -n 20 || true

# ----------------------------------------------------------------------
# 3. run the pipeline once (defaults) and then once with the homography
#    comparison, so the performance lab has two records with different settings
# ----------------------------------------------------------------------
echo ">>> starting a default run"
run1=$(curl -s --max-time 30 -X POST "$BASE/api/runs" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg s "$SOURCE_FOLDER" --arg n "Demo: Brighton Beach (affine)" --arg p "laptop" \
        '{source: $s, name: $n, settings: {profile: $p}}')")
run_id1=$(jq -r .run_id <<< "$run1")
echo "   run_id=$run_id1"

echo ">>> streaming the first run (this takes a few minutes)"
t0=$(date +%s)
curl -s --max-time 1800 "$BASE/api/runs/$run_id1/events" | python -c "
import sys, json, time
start = time.time()
for raw in sys.stdin:
    line = raw.decode('utf-8','replace').strip()
    if not line.startswith('data:'):
        continue
    try:
        ev = json.loads(line[5:].strip())
    except Exception:
        continue
    kind = ev.get('type')
    if kind == 'stage':
        print(f\"  {ev['stage']['name']:<15} {ev['stage']['status']:<8} {ev['stage']['detail'] or ''}\")
    elif kind == 'first_tile':
        print(f\"  first tile written after {ev.get('seconds'):.2f}s\")
    elif kind == 'finished':
        print(f\"  run {ev.get('status')}\")
        break
    if time.time() - start > 1680:
        print('  (stream timed out; poll on the report)')
        break
"
t1=$(date +%s)
echo "   first run done in $((t1 - t0)) seconds"

# wait a moment for the report to be fully written
sleep 2

echo ">>> validating the first run's artifacts"
python - "$run_id1" "$BASE" <<'PY'
import sys, json, urllib.request
from pathlib import Path

run_id = sys.argv[1]
base = sys.argv[2]

report = json.loads(urllib.request.urlopen(f"{base}/api/runs/{run_id}/report.json", timeout=60).read())
metrics = report.get("metrics") or {}
output = report.get("output") or {}
print(f"   status={report['status']} wall={metrics.get('wall_clock_s')}s peak_rss={metrics.get('peak_rss_mb')}MB")
print(f"   frames accepted={metrics.get('frames_accepted')} rejected={metrics.get('frames_rejected')} "
      f"failed={metrics.get('frames_failed')} composed={metrics.get('frames_composed')}")
print(f"   pairs candidate={metrics.get('pairs_candidates')} matched={metrics.get('pairs_matched')} "
      f"failed={metrics.get('pairs_failed')} inliers={metrics.get('total_inliers')}")
print(f"   output kind={output.get('kind')} produced={output.get('produced')} bytes={metrics.get('output_bytes')}")

geotiff = output.get("geotiff_path")
if geotiff and Path(geotiff).exists():
    import rasterio
    with rasterio.open(geotiff) as src:
        print(f"   GeoTIFF {src.width}x{src.height} {src.crs} px={abs(src.transform.a)}m bands={src.count} "
              f"nodata={src.nodata} tiled={src.is_tiled} overviews={src.overviews(1)}")

cog = output.get("cog_path")
if cog and Path(cog).exists():
    import rasterio
    with rasterio.open(cog) as src:
        print(f"   COG {src.count} bands px={abs(src.transform.a)}m tiled={src.is_tiled} "
              f"overviews={src.overviews(1)} mask={bool(src.mask_flag_enums)}")

tiles_dir = output.get("tiles_dir")
if tiles_dir:
    tiles = sorted(Path(tiles_dir).rglob("*.png"))
    print(f"   XYZ tiles on disk: {len(tiles)} (reported {output.get('tile_count')}) "
          f"z{output.get('min_zoom')}-z{output.get('max_zoom')}")

for kind in ("metadata_json", "frames_csv", "report_json", "metrics_csv"):
    art = next((a for a in report.get("artifacts") or [] if a["kind"] == kind), None)
    if art:
        ok = Path(art["path"]).exists()
        print(f"   {kind}: exists={ok} ({art['path']})")
PY

echo ">>> the first run report: $BASE/api/runs/$run_id1/report.json"
curl -s --max-time 30 "$BASE/api/runs/$run_id1/report.json" | python -c "import json,sys; d=json.load(sys.stdin); print(json.dumps({k:v for k,v in d.items() if k not in ('stages','alignment','alignment_comparison','frames','geojson','pairs')}, indent=2)[:900])"

# ----------------------------------------------------------------------
# 4. a second run with the homography comparison (so the performance lab has
#    a comparison record), using the pi-class profile
# ----------------------------------------------------------------------
echo ">>> starting a second run: Brighton Beach (pi-class, affine + homography)"
run2=$(curl -s --max-time 30 -X POST "$BASE/api/runs" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg s "$SOURCE_FOLDER" --arg n "Demo: Brighton Beach (pi-class, affine+homography)" \
        '{source: $s, name: $n, settings: {profile: "pi-class", alignment_model: "both"}}')")
run_id2=$(jq -r .run_id <<< "$run2")
echo "   run_id=$run_id2"

echo ">>> streaming the second run"
curl -s --max-time 1800 "$BASE/api/runs/$run_id2/events" | python -c "
import sys, json, time
for raw in sys.stdin:
    line = raw.decode('utf-8','replace').strip()
    if not line.startswith('data:'):
        continue
    try:
        ev = json.loads(line[5:].strip())
    except Exception:
        continue
    kind = ev.get('type')
    if kind == 'stage':
        print(f\"  {ev['stage']['name']:<15} {ev['stage']['status']:<8} {ev['stage']['detail'] or ''}\")
    elif kind == 'first_tile':
        print(f\"  first tile written after {ev.get('seconds'):.2f}s\")
    elif kind == 'finished':
        print(f\"  run {ev.get('status')}\")
        break
"
sleep 2

echo ">>> validating the second run's artifacts"
python - "$run_id2" "$BASE" <<'PY'
import sys, json, urllib.request
from pathlib import Path
import rasterio

run_id = sys.argv[1]
base = sys.argv[2]
report = json.loads(urllib.request.urlopen(f"{base}/api/runs/{run_id}/report.json", timeout=60).read())
metrics = report.get("metrics") or {}
output = report.get("output") or {}
print(f"   status={report['status']} wall={metrics.get('wall_clock_s')}s peak_rss={metrics.get('peak_rss_mb')}MB")
print(f"   frames accepted={metrics.get('frames_accepted')} rejected={metrics.get('frames_rejected')} "
      f"failed={metrics.get('frames_failed')} composed={metrics.get('frames_composed')}")
print(f"   pairs candidate={metrics.get('pairs_candidates')} matched={metrics.get('pairs_matched')} "
      f"failed={metrics.get('pairs_failed')} inliers={metrics.get('total_inliers')}")

geotiff = output.get("geotiff_path")
if geotiff and Path(geotiff).exists():
    with rasterio.open(geotiff) as src:
        print(f"   GeoTIFF {src.width}x{src.height} {src.crs} px={abs(src.transform.a)}m bands={src.count} "
              f"nodata={src.nodata} tiled={src.is_tiled} overviews={src.overviews(1)}")

cog = output.get("cog_path")
if cog and Path(cog).exists():
    with rasterio.open(cog) as src:
        print(f"   COG {src.count} bands px={abs(src.transform.a)}m tiled={src.is_tiled} "
              f"overviews={src.overviews(1)} mask={bool(src.mask_flag_enums)}")

tiles_dir = output.get("tiles_dir")
if tiles_dir:
    tiles = sorted(Path(tiles_dir).rglob("*.png"))
    print(f"   XYZ tiles on disk: {len(tiles)} (reported {output.get('tile_count')}) "
          f"z{output.get('min_zoom')}-z{output.get('max_zoom')}")

if report.get("comparison"):
    c = report["comparison"]
    print(f"   homomorphic comparison: available={c.get('available')}")
    print(f"      similarity mean gps error: {c.get('similarity',{}).get('mean_gps_error_m')} m")
    print(f"      homography mean gps error: {c.get('homography_chain',{}).get('mean_gps_error_m')} m")
    print(f"      placement disagreement: {c.get('mean_placement_disagreement_m')} m")
    print(f"      homography pairs ok: {c.get('homography_pairs_ok')} / {c.get('homography_pairs_attempted')}")
PY

echo ">>> the second run report: $BASE/api/runs/$run_id2/report.json"
curl -s --max-time 30 "$BASE/api/runs/$run_id2/report.json" | python -c "import json,sys; d=json.load(sys.stdin); print(json.dumps({k:v for k,v in d.items() if k not in ('stages','alignment','alignment_comparison','frames','geojson','pairs')}, indent=2)[:900])"

# ----------------------------------------------------------------------
# 5. the performance lab records
# ----------------------------------------------------------------------
echo ">>> performance records on this machine"
curl -s --max-time 60 "$BASE/api/performance" | python -c "
import json,sys
d = json.load(sys.stdin)
print(f\"{d['count']} records, rates Mbps={d['bandwidth_rates_mbps']}\")
for r in d['records']:
    print(f\"  {r['name'][:44]:46s} {r['profile']:8s} wall={r['wall_clock_s']:.1f}s rss={r['peak_rss_mb']:.0f}MB frames={r['frames_accepted']} ttft={r.get('time_to_first_tile_s',0):.2f}s\")
    b = r.get('bandwidth',{})
    for k,v in b.get('scenarios',{}).items():
        print(f\"        {k} Mbps: input {v.get('input_human')} web {v.get('web_human')} diff {v.get('web_saved_human')} everything {v.get('output_human')}\")
    if b.get('web_saved_human') and b['web_saved_human'].startswith('-'):
        print('      -- web delivery: products larger than input (no saving claimed for this series)')
    if b.get('web_reduction_factor'):
        print(f\"      web reduction {b['web_reduction_factor']:.2f}x (raw/web)\")
    if r.get('comparison'):
        c = r['comparison']
        print(f\"      comparison: homog pairs {c.get('homography_pairs_ok')}/{c.get('homography_pairs_attempted')}, sim gps {c.get('similarity',{}).get('mean_gps_error_m')} m, homog gps {c.get('homography_chain',{}).get('mean_gps_error_m')} m\")
    if r.get('measurements_unavailable'):
        print(f\"      unavailable: {r['measurements_unavailable']}\")
    print()
"

echo ">>> demo script complete"
echo "   backend: $BASE"
echo "   runs: $run_id1 (affine, laptop), $run_id2 (affine+homography, pi-class)"
echo "   report 1: $BASE/api/runs/$run_id1/report.json"
echo "   report 2: $BASE/api/runs/$run_id2/report.json"
echo "   performance: $BASE/api/performance"
