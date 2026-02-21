#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    echo ""
    echo "Shutting down..."
    [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null && echo "  Backend stopped"
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null && echo "  Frontend stopped"
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

echo "========================================="
echo "  Smart-LaTeX Development Server"
echo "========================================="

# ------------------------------------------
# Activate Python venv
# ------------------------------------------
if [ -d "$BACKEND_DIR/venv" ]; then
    source "$BACKEND_DIR/venv/bin/activate"
else
    echo "[ERROR] Python venv not found. Run ./install.sh first."
    exit 1
fi

# ------------------------------------------
# Start backend (uvicorn)
# ------------------------------------------
echo ""
echo "Starting backend server..."
cd "$BACKEND_DIR"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
echo "  Backend PID: $BACKEND_PID"

# ------------------------------------------
# Start frontend (vite dev)
# ------------------------------------------
echo ""
echo "Starting frontend dev server..."
cd "$FRONTEND_DIR"
npm run dev -- --host 0.0.0.0 --port 5173 &
FRONTEND_PID=$!
echo "  Frontend PID: $FRONTEND_PID"

# ------------------------------------------
# Print access URLs
# ------------------------------------------
echo ""
echo "========================================="
echo "  Services running:"
echo ""
echo "  Frontend:  http://localhost:5173"
echo "  Backend:   http://localhost:8000"
echo "  API Docs:  http://localhost:8000/docs"
echo ""
echo "  Press Ctrl+C to stop all services"
echo "========================================="

# Wait for background processes
wait
