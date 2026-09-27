#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "=== ruff check ==="
ruff check src/ tests/
echo "=== ruff format --check ==="
ruff format --check src/ tests/
echo "=== pyright ==="
pyright
echo "=== pytest ==="
pytest
echo "=== shellcheck ==="
shellcheck run.sh check.sh
echo "=== shfmt ==="
shfmt -d run.sh check.sh
