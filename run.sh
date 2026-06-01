#!/usr/bin/env bash
# AEOLUS — one-command launcher. Builds the pipeline (if needed), then starts
# the API and the dashboard. Ctrl-C stops both.
set -e
cd "$(dirname "$0")"

PY=.venv/bin/python
if [ ! -x "$PY" ]; then
  echo "Creating venv + installing backend deps..."
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r backend/requirements.txt
fi

if [ ! -f data/gold/approvals.json ]; then
  echo "Building pipeline (M0->M5)... first run downloads ~95MB SCADA + trains models."
  (cd backend && PYTHONWARNINGS=ignore ../$PY -m aeolus.pipeline)
fi

echo "Starting API on :8000 and dashboard on :5173 ..."
(cd backend && PYTHONWARNINGS=ignore ../$PY -m uvicorn aeolus.api.main:app --port 8000) &
API_PID=$!
(cd frontend && npm install --silent && npm run dev) &
WEB_PID=$!

trap "kill $API_PID $WEB_PID 2>/dev/null" EXIT
echo "AEOLUS up -> http://localhost:5173"
wait
