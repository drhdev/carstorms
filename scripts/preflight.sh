#!/usr/bin/env bash
# Local mirror of .github/workflows/ci.yml — run before every commit/push so CI
# never fails on formatting, lint, types or tests.
#
# Steps 1-2 auto-fix; steps 3-6 are the exact gates CI runs (check-only).
set -euo pipefail

# uv is installed under ~/.local/bin by the standalone installer.
export PATH="$HOME/.local/bin:$PATH"

cd "$(dirname "$0")/.."

echo "==> (1/6) ruff format (auto-fix)"
uv run ruff format .

echo "==> (2/6) ruff check --fix (auto-fix lint)"
uv run ruff check --fix .

echo "==> (3/6) ruff format --check  [CI gate]"
uv run ruff format --check .

echo "==> (4/6) ruff check  [CI gate]"
uv run ruff check .

echo "==> (5/6) mypy src  [CI gate]"
uv run mypy src

echo "==> (6/6) pytest  [CI gate]"
uv run pytest

echo
echo "✅ preflight passed — safe to commit and push."
if ! git diff --quiet; then
  echo "ℹ️  Auto-format/lint changed files — 'git add -A' before committing."
fi
