#!/usr/bin/env bash
set -euo pipefail

# =========================================
#  Smart-LaTeX 启动脚本
# =========================================

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIST="$PROJECT_ROOT/frontend/dist"
PORT="${PORT:-8000}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check venv
if [ ! -d "$BACKEND_DIR/venv" ]; then
    echo -e "${RED}[ERROR]${NC} 未找到虚拟环境，请先运行: ./install.sh"
    exit 1
fi

# Check .env
if [ ! -f "$BACKEND_DIR/.env" ]; then
    echo -e "${RED}[ERROR]${NC} 未找到配置文件，请先运行: ./install.sh"
    exit 1
fi

# Check frontend build
if [ ! -d "$FRONTEND_DIST" ]; then
    echo -e "${YELLOW}[WARN]${NC} 前端未构建，正在构建..."
    cd "$PROJECT_ROOT/frontend" && npm run build
fi

# Activate venv
source "$BACKEND_DIR/venv/bin/activate"

echo ""
echo "========================================="
echo -e "  ${GREEN}Smart-LaTeX${NC} 正在启动..."
echo ""
echo "  访问地址: http://localhost:$PORT"
echo "  API 文档: http://localhost:$PORT/docs"
echo ""
echo "  按 Ctrl+C 停止服务"
echo "========================================="
echo ""

cd "$BACKEND_DIR"
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
