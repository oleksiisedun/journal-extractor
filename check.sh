#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "=== ruff check ==="
ruff check src/
echo "=== ruff format --check ==="
ruff format --check src/
echo "=== pyright ==="
pyright src/
echo "=== shellcheck ==="
shellcheck run.sh check.sh
echo "=== shfmt ==="
shfmt -d run.sh check.sh
