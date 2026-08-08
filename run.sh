#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
python3 src/generate_extract.py "$@"
