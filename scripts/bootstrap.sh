#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CACHE_ROOT="${XDG_CACHE_HOME:-${REPO_ROOT}/.cache}"
NODE_VERSION="${NODE_VERSION:-$(cat "${REPO_ROOT}/.node-version" 2>/dev/null || echo "24.6.0")}" 
PYTHON_BIN="${PYTHON:-python3}"

mkdir -p "${CACHE_ROOT}" "${CACHE_ROOT}/npm" "${CACHE_ROOT}/pip"

if command -v fnm >/dev/null 2>&1; then
  eval "$(fnm env --use-on-cd)"
  fnm install "${NODE_VERSION}"
  fnm use "${NODE_VERSION}"
elif command -v volta >/dev/null 2>&1; then
  volta install "node@${NODE_VERSION}"
elif command -v nvm >/dev/null 2>&1; then
  # shellcheck disable=SC1090
  if [ -s "${HOME}/.nvm/nvm.sh" ]; then
    . "${HOME}/.nvm/nvm.sh"
  fi
  nvm install "${NODE_VERSION}"
  nvm use "${NODE_VERSION}"
else
  echo "[bootstrap] nodeバージョンマネージャー(fnm/volta/nvm)が見つかりません。既存のnodeを利用します。" >&2
fi

export npm_config_cache="${CACHE_ROOT}/npm"
cd "${REPO_ROOT}"

if [ -f package-lock.json ]; then
  npm ci
else
  npm install
fi

if command -v npx >/dev/null 2>&1; then
  npx --yes playwright install >/dev/null 2>&1 || echo "[bootstrap] playwrightブラウザのインストールをスキップしました" >&2
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "[bootstrap] Python(${PYTHON_BIN}) が見つかりません" >&2
  exit 1
fi

VENV_DIR="${REPO_ROOT}/.venv"
if [ ! -d "${VENV_DIR}" ]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
export PIP_CACHE_DIR="${CACHE_ROOT}/pip"
pip install --upgrade pip
pip install -r "${REPO_ROOT}/projects/04-llm-adapter-shadow/requirements.txt"
deactivate
