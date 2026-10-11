#!/usr/bin/env bash
# Run backend (background, logs -> backend.log) + frontend (foreground) locally.
# Works from any directory. Ctrl+C stops both.
cd "$(dirname "$(readlink -f "$0")")" || exit 1

# Vite 5 needs Node >= 18; system node may be older, so switch via nvm (see frontend/.nvmrc).
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm use "$(cat frontend/.nvmrc)" >/dev/null

(cd backend && source venv/bin/activate && exec uvicorn main:app --reload --port 8000) > backend.log 2>&1 &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null' EXIT
trap 'exit 130' INT TERM

echo -n "Waiting for backend on http://localhost:8000 (logs: backend.log) "
until curl -s -o /dev/null http://localhost:8000/api/status; do
  kill -0 $BACKEND_PID 2>/dev/null || { echo; echo "Backend failed to start:"; tail -20 backend.log; exit 1; }
  echo -n "."; sleep 1
done
echo " ready"
cd frontend && npm run dev
