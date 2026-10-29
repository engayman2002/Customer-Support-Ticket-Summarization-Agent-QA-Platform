#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "================================================================================"
echo "  Starting Customer Support Ticket Summarization & Agent QA Platform (Dev Mode)"
echo "================================================================================"

echo "[1/3] Ensuring PostgreSQL 16 and Redis 7 containers are healthy..."
docker compose up -d postgres redis

echo "[2/3] Starting FastAPI Backend on http://0.0.0.0:8000 ..."
PYTHONPATH="$ROOT_DIR/backend" uvicorn app.main:app --app-dir "$ROOT_DIR/backend" --host 0.0.0.0 --port 8000 &
FASTAPI_PID=$!

echo "[3/3] Starting Next.js 15 Frontend on http://0.0.0.0:3000 ..."
cd "$ROOT_DIR/frontend"
npm run dev -- --hostname 0.0.0.0 --port 3000 &
NEXT_PID=$!

trap 'echo "Stopping FastAPI ($FASTAPI_PID) and Next.js ($NEXT_PID)..."; kill $FASTAPI_PID $NEXT_PID 2>/dev/null || true' EXIT INT TERM

echo ""
echo "Platform is live:"
echo "  • Next.js 15 UI : http://localhost:3000"
echo "  • FastAPI Docs  : http://localhost:8000/docs"
echo ""
wait

