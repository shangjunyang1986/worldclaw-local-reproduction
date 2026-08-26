#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
uv_bin="$(command -v uv || true)"
if [[ -z "${uv_bin}" ]]; then
  echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi
command -v npm >/dev/null || { echo "npm is required." >&2; exit 1; }

"${uv_bin}" venv --allow-existing --python 3.12 "${project_root}/webapp/.venv"
"${uv_bin}" pip install --python "${project_root}/webapp/.venv/bin/python" \
  --editable "${project_root}[web,dev]"
npm ci --prefix "${project_root}/webapp/frontend"
npm run build --prefix "${project_root}/webapp/frontend"
"${project_root}/webapp/.venv/bin/python" "${project_root}/scripts/check_web_environment.py"

echo "WorldClaw Studio is installed. Run scripts/start_web.sh"
