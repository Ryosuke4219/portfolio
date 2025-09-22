#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

pushd "${REPO_ROOT}" > /dev/null

node scripts/serve-static.mjs projects/02-llm-to-playwright/demo 5173 &
SERVER_PID=$!

cleanup() {
  if kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

READY=false
for _ in $(seq 1 30); do
  if curl -sSf http://localhost:5173 >/dev/null 2>&1; then
    READY=true
    break
  fi
  sleep 1
done

if [ "${READY}" != "true" ]; then
  echo "[node-suite] Demo server failed to start" >&2
  exit 1
fi

BASE_URL=http://localhost:5173 npm test

popd > /dev/null
