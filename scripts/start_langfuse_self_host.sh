#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"
docker compose \
  --env-file .env.langfuse \
  -f docker-compose.langfuse.yml \
  up -d

echo "Langfuse is starting on http://localhost:${LANGFUSE_WEB_PORT:-3000}"
