#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment variables from .env if it exists.
if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${ROOT_DIR}/.env"
  set +a
fi

export DISCORD_TOKEN="${DISCORD_TOKEN:-}"
export DISCORD_CHANNEL_ID="${DISCORD_CHANNEL_ID:-}"
export ENABLE_LLM="${ENABLE_LLM:-true}"
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
export OPENROUTER_SQL_MODEL="${OPENROUTER_SQL_MODEL:-openai/gpt-4o-mini}"
export OPENROUTER_SUMMARY_MODEL="${OPENROUTER_SUMMARY_MODEL:-openai/gpt-4o-mini}"

if [[ -z "${DISCORD_TOKEN}" || -z "${DISCORD_CHANNEL_ID}" ]]; then
  echo "Missing DISCORD_TOKEN or DISCORD_CHANNEL_ID." >&2
  exit 1
fi

if [[ "${ENABLE_LLM}" == "true" && -z "${OPENROUTER_API_KEY}" ]]; then
  echo "ENABLE_LLM=true but OPENROUTER_API_KEY is missing." >&2
  exit 1
fi

if [[ -f "${ROOT_DIR}/venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source "${ROOT_DIR}/venv/bin/activate"
else
  echo "Virtualenv not found at ${ROOT_DIR}/venv." >&2
  exit 1
fi

exec python "${ROOT_DIR}/bot_with_llm.py"
