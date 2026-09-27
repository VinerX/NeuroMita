#!/usr/bin/env bash
set -euo pipefail

testbed_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
adapter_dir="$(cd -- "$testbed_dir/../external_tts_adapter" && pwd)"
: "${NEUROMITA_API_KEY:?Export NEUROMITA_API_KEY before starting the testbed}"

python3 -c 'import aiohttp' || {
    echo "Missing adapter dependency. Install it with: sudo apt-get install python3-aiohttp" >&2
    exit 1
}
PYTHONPATH="$adapter_dir" python3 -c 'import adapter'

mkdir -p "$testbed_dir/artifacts"
config_file="$(mktemp /tmp/neuromita-external-tts.XXXXXX.json)"
pids=()

cleanup() {
    for pid in "${pids[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    for pid in "${pids[@]}"; do
        wait "$pid" 2>/dev/null || true
    done
    rm -f -- "$config_file"
}
trap cleanup EXIT INT TERM

python3 - "$testbed_dir/adapter.test.json" "$config_file" <<'PY'
import json
import sys

source, target = sys.argv[1:]
with open(source, encoding="utf-8") as stream:
    config = json.load(stream)
for stage in config["stages"]:
    stage["url"] = stage["url"].replace("mock-f5", "127.0.0.1").replace("mock-rvc", "127.0.0.1")
with open(target, "w", encoding="utf-8") as stream:
    json.dump(config, stream)
PY
chmod 600 "$config_file"

python3 "$testbed_dir/mock_upstream.py" --stage f5 --host 127.0.0.1 --port 8001 \
    >"$testbed_dir/artifacts/mock-f5.log" 2>&1 &
pids+=("$!")
python3 "$testbed_dir/mock_upstream.py" --stage rvc --host 127.0.0.1 --port 8002 \
    >"$testbed_dir/artifacts/mock-rvc.log" 2>&1 &
pids+=("$!")

python3 - "$testbed_dir" "$config_file" "$NEUROMITA_API_KEY" <<'PY' \
    >"$testbed_dir/artifacts/adapter.log" 2>&1 &
import os
import sys
from pathlib import Path

testbed, config, api_key = sys.argv[1:]
adapter_dir = Path(testbed).parent / "external_tts_adapter"
sys.path.insert(0, str(adapter_dir))
os.environ["ADAPTER_CONFIG"] = config
os.environ["NEUROMITA_API_KEY"] = api_key
os.environ["PYTHONPATH"] = str(adapter_dir)
os.environ["PORT"] = "8080"
import aiohttp.web
import adapter

aiohttp.web.run_app(adapter.create_app(), host="127.0.0.1", port=8080)
PY
pids+=("$!")

python3 - <<'PY'
import time
import urllib.error
import urllib.request

for url in ("http://127.0.0.1:8001/health", "http://127.0.0.1:8002/health"):
    deadline = time.monotonic() + 20
    while True:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    break
        except (urllib.error.URLError, TimeoutError):
            if time.monotonic() >= deadline:
                raise RuntimeError(f"mock stage did not start: {url}")
            time.sleep(0.25)
PY

python3 "$testbed_dir/smoke_test.py" \
    --base-url http://127.0.0.1:8080 \
    --api-key "$NEUROMITA_API_KEY" \
    --artifact-dir "$testbed_dir/artifacts"
