---
name: preflight
description: Run the full CI gate locally before committing or pushing — ruff format, ruff lint, mypy, and pytest, matching .github/workflows/ci.yml exactly. ALWAYS use this before `git push` (and after finishing code changes) so GitHub CI never fails on formatting/lint/type/test. Also triggers on "preflight", "check CI", "verify before push", "is this CI-green".
---

# Preflight — match GitHub CI locally before pushing

GitHub CI (`.github/workflows/ci.yml`) fails the build if any of `ruff check`,
`ruff format --check`, `mypy src`, or `pytest` is not clean. A common failure is
`ruff format --check` reporting "Would reformat: …" when a file wasn't formatted.
This skill runs the same gates locally first.

## Always run before pushing

```bash
bash scripts/preflight.sh
```

It runs, in order:
1. `uv run ruff format .` — auto-format (prevents the "would reformat" CI failure)
2. `uv run ruff check --fix .` — lint with autofix
3. `uv run ruff format --check .` — **CI gate** (formatting must be clean)
4. `uv run ruff check .` — **CI gate** (lint must be clean)
5. `uv run mypy src` — **CI gate** (types)
6. `uv run pytest` — **CI gate** (tests)

## Rules

- **Do not `git push` unless the script exits 0** (prints "✅ preflight passed").
- Steps 1–2 may modify files. If so, `git add -A` and include them in the commit
  **before** pushing — otherwise CI sees the unformatted version and fails.
- If a gate fails, fix the cause and re-run `scripts/preflight.sh`; never push a red tree.
- The proper place to run this is **before** creating the commit, so any
  auto-format changes are part of that commit.

## Optional: enforce automatically

To make this unskippable, install it as a git pre-push hook:

```bash
ln -sf ../../scripts/preflight.sh .git/hooks/pre-push && chmod +x scripts/preflight.sh
```
