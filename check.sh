#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "=== ruff check ==="
uv run ruff check src/ tests/
echo "=== ruff format --check ==="
uv run ruff format --check src/ tests/
echo "=== pyright ==="
uv run pyright
echo "=== pytest ==="
uv run pytest
echo "=== shellcheck ==="
shellcheck run.sh check.sh
echo "=== shfmt ==="
shfmt -d run.sh check.sh
