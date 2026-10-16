#!/bin/sh
# For Codex cloud development, not an HAOS host command.
set -eu
cd /workspace/ha-ring-face-recognition
export UV_CACHE_DIR=/tmp/ring-uv UV_LINK_MODE=copy
uv venv --allow-existing .venv
uv pip install --python .venv/bin/python --require-hashes -r ring_face/requirements.lock
uv pip install --python .venv/bin/python -r requirements-dev.txt
python scripts/build_cloud.py
mkdir -p /workspace/ring-models
container_id=$(docker create ring-face:0.1.3)
trap 'docker rm "$container_id" >/dev/null' EXIT HUP INT TERM
docker cp "$container_id:/opt/models/." /workspace/ring-models/
python ring_face/fetch_models.py /workspace/ring-models
python scripts/fetch_sample.py /workspace/ring-lena.jpg
.venv/bin/python scripts/check.py
RING_TEST_MODELS=/workspace/ring-models RING_TEST_IMAGE=/workspace/ring-lena.jpg .venv/bin/python -m pytest -q
