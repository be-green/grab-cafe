#!/usr/bin/env bash

ROOT_DIR="/root/grab-cafe"
cd "$ROOT_DIR"

export DISCORD_TOKEN=""
export DISCORD_CHANNEL_ID=""
export ENABLE_LLM="${ENABLE_LLM:-true}"
export OPENROUTER_API_KEY=""
export OPENROUTER_SQL_MODEL="openai/gpt-oss-120b"
export OPENROUTER_SUMMARY_MODEL="openai/gpt-oss-120b"

source "$ROOT_DIR/venv/bin/activate"
python3 "$ROOT_DIR/bot_with_llm.py"