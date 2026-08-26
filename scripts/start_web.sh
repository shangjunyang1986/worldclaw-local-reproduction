#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
web_python="${WORLDCLAW_WEB_PYTHON:-${project_root}/webapp/.venv/bin/python}"
host="${WORLDCLAW_HOST:-127.0.0.1}"
port="${WORLDCLAW_PORT:-7865}"
api_token="${WORLDCLAW_API_TOKEN:-}"

[[ -x "${web_python}" ]] || { echo "Run scripts/setup_web.sh first." >&2; exit 1; }
[[ -f "${project_root}/webapp/frontend/dist/index.html" ]] || {
  echo "Frontend build is missing. Run scripts/setup_web.sh first." >&2
  exit 1
}
if [[ "${host}" != "127.0.0.1" && "${host}" != "localhost" && "${host}" != "::1" && ${#api_token} -lt 24 ]]; then
  echo "Refusing non-loopback binding without WORLDCLAW_API_TOKEN (at least 24 characters)." >&2
  exit 1
fi

cd "${project_root}"
exec "${web_python}" -m uvicorn webapp.backend.app:app \
  --host "${host}" --port "${port}" --workers 1
