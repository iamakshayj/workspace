#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

exec "$ROOT_DIR/.local/llama/llama-server" \
  --model "$ROOT_DIR/.models/Qwen3-4B-Q4_K_M.gguf" \
  --alias qwen3-4b-local \
  --api-key local-model \
  --host 127.0.0.1 \
  --port 8001 \
  --ctx-size 8192 \
  --n-gpu-layers 99
