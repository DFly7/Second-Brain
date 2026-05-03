#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

docker compose run --rm \
  -v "$SCRIPT_DIR:/marker-export-out" \
  -v "$SCRIPT_DIR/download_marker_exports.py:/dl.py:ro" \
  api python /dl.py
