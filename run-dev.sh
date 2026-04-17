#!/usr/bin/env bash
# Starts the backend with a clean ANTHROPIC_API_KEY so pydantic-settings
# loads the value from .env instead of inheriting an empty one from the
# Claude Desktop parent process.
set -e
cd "$(dirname "$0")"
unset ANTHROPIC_API_KEY
exec make dev
