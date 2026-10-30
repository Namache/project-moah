#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v npm >/dev/null 2>&1; then
  printf 'npm is required to run the frontend. Install Node.js and npm, then retry.\n' >&2
  exit 1
fi
cd "$repo_root/frontend"
exec npm run dev
