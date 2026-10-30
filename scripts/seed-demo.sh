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
exec "$python_bin" -m app.seed
