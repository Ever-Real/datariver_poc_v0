#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
modelfile="$root/infra/ollama/Modelfile.gemma4-mac-dev"
base_model="gemma4:e2b-it-qat"
development_model="datariver-gemma4-dev:0.1"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is required. Install/start native macOS Ollama before preparing the model." >&2
  exit 2
fi

if [ ! -f "$modelfile" ]; then
  echo "Missing local Ollama Modelfile: $modelfile" >&2
  exit 2
fi

# This is a native host operation. It intentionally does not start an Ollama
# container: Docker Desktop callers use host.docker.internal instead.
if ! ollama show "$base_model" >/dev/null 2>&1; then
  ollama pull "$base_model"
fi
ollama create "$development_model" -f "$modelfile"
ollama show "$development_model" >/dev/null

echo "Prepared $development_model with an 8192-token context limit."
