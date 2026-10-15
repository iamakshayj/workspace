#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
RUNTIME_ARCHIVE="/tmp/llama-b10516-bin-macos-arm64.tar.gz"

mkdir -p "$ROOT_DIR/.local/llama" "$ROOT_DIR/.models"

curl -fL \
  "https://github.com/ggml-org/llama.cpp/releases/download/b10516/llama-b10516-bin-macos-arm64.tar.gz" \
  -o "$RUNTIME_ARCHIVE"
tar -xzf "$RUNTIME_ARCHIVE" -C "$ROOT_DIR/.local/llama" --strip-components=1

curl -fL \
  "https://huggingface.co/ggml-org/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf?download=true" \
  -o "$ROOT_DIR/.models/Qwen3-4B-Q4_K_M.gguf"

echo "Local runtime and Qwen3-4B Q4 model installed."
echo "Start it with: ./scripts/start-local-model.sh"
