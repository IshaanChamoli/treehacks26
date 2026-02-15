#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT="${API_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
API_HOST="${API_HOST:-127.0.0.1}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://${API_HOST}:${API_PORT}}"
API_PYTHON="${API_PYTHON:-}"

if [[ -z "${API_PYTHON}" ]]; then
  if [[ -x "${ROOT_DIR}/api/.venv/bin/python" ]]; then
    API_PYTHON="${ROOT_DIR}/api/.venv/bin/python"
  else
    API_PYTHON="python3"
  fi
fi

if [[ ! -f "${ROOT_DIR}/api/.env" && ( -z "${ELASTICSEARCH_URL:-}" || -z "${ELASTICSEARCH_API_KEY:-}" ) ]]; then
  echo "Missing backend config: create api/.env from api/.env.example (or export ELASTICSEARCH_URL and ELASTICSEARCH_API_KEY)."
  exit 1
fi

cleanup() {
  local exit_code=$?
  if [[ -n "${API_PID:-}" ]]; then
    kill "${API_PID}" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]]; then
    kill "${FRONTEND_PID}" 2>/dev/null || true
  fi
  wait "${API_PID:-}" "${FRONTEND_PID:-}" 2>/dev/null || true
  exit "${exit_code}"
}

trap cleanup INT TERM EXIT

(
  cd "${ROOT_DIR}/api"
  "${API_PYTHON}" -m uvicorn app.main:app --host "${API_HOST}" --port "${API_PORT}"
) &
API_PID=$!

(
  cd "${ROOT_DIR}/frontend"
  NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL}" npm run dev -- --hostname "${FRONTEND_HOST}" --port "${FRONTEND_PORT}"
) &
FRONTEND_PID=$!

echo "API:      http://${API_HOST}:${API_PORT}"
echo "Frontend: http://${FRONTEND_HOST}:${FRONTEND_PORT}"

while true; do
  if ! kill -0 "${API_PID}" 2>/dev/null; then
    wait "${API_PID}"
    exit $?
  fi

  if ! kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    wait "${FRONTEND_PID}"
    exit $?
  fi

  sleep 1
done
