#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PROJECT_BRAIN_PYTHON:-}"
if [[ -z "$python_bin" && -x "$repo_root/.venv/bin/python" ]]; then
  python_bin="$repo_root/.venv/bin/python"
elif [[ -z "$python_bin" ]]; then
  python_bin="python3"
fi

cd "$repo_root/backend"
"$python_bin" -m pytest
"$python_bin" -m ruff check .
"$python_bin" -m ruff format --check .

if ! command -v npm >/dev/null 2>&1; then
  printf 'npm is required for frontend checks. Install Node.js and npm, then retry.\n' >&2
  exit 1
fi
cd "$repo_root/frontend"
npm run check
npm run test
npm run build
