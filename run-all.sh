#!/usr/bin/env bash
# Start every backend process, in one terminal.
#   ./run-all.sh
# Ctrl-C stops all of them. The frontend lives in its own repo; run it there
# with `npm run dev`.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> infrastructure"
docker compose up -d
until docker exec gradportal-db pg_isready -U gradportal >/dev/null 2>&1; do sleep 1; done

pids=()
cleanup() { echo; echo "==> stopping"; for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

echo "==> core-api      :8000"
(cd backend  && .venv/bin/uvicorn app.main:app --reload --port 8000) & pids+=($!)
echo "==> doc-service   :8001"
(cd services && .venv/bin/uvicorn doc_service.main:app   --reload --port 8001) & pids+=($!)
echo "==> rag-service   :8002"
(cd services && .venv/bin/uvicorn rag_service.main:app   --reload --port 8002) & pids+=($!)
echo "==> eval-service  :8003"
(cd services && .venv/bin/uvicorn eval_service.main:app  --reload --port 8003) & pids+=($!)
echo "==> voice-service :8004"
(cd services && .venv/bin/uvicorn voice_service.main:app --reload --port 8004) & pids+=($!)
echo "==> worker"
(cd backend  && .venv/bin/arq app.workers.main.WorkerSettings) & pids+=($!)

cat <<'BANNER'

  core-api    http://localhost:8000/docs
  doc         http://localhost:8001/docs
  rag         http://localhost:8002/docs
  eval        http://localhost:8003/docs
  voice       http://localhost:8004/docs
  mailpit     http://localhost:8025

BANNER
wait
