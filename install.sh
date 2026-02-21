#!/usr/bin/env bash
set -euo pipefail

# =========================================
#  Smart-LaTeX 一键安装脚本 (macOS / Linux)
#  v1.0.0
# =========================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; }

echo ""
echo "========================================="
echo "  Smart-LaTeX 一键安装 v1.0.0"
echo "========================================="
echo ""

# ------------------------------------------
# 1. 检查系统依赖
# ------------------------------------------
info "检查系统依赖..."

MISSING=()

# Python 3.10+
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
        ok "Python $PY_VER"
    else
        fail "Python $PY_VER (需要 3.10+)"
        MISSING+=("python3.10+")
    fi
else
    fail "Python3 未安装"
    MISSING+=("python3")
fi

# Node.js 18+
if command -v node &>/dev/null; then
    NODE_VER=$(node -v | sed 's/v//')
    NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
    if [ "$NODE_MAJOR" -ge 18 ]; then
        ok "Node.js $NODE_VER"
    else
        fail "Node.js $NODE_VER (需要 18+)"
        MISSING+=("node18+")
    fi
else
    fail "Node.js 未安装"
    MISSING+=("node")
fi

# npm
if command -v npm &>/dev/null; then
    ok "npm $(npm -v)"
else
    fail "npm 未安装"
    MISSING+=("npm")
fi

# Pandoc (Word 导出)
if command -v pandoc &>/dev/null; then
    ok "pandoc $(pandoc --version | head -1 | awk '{print $2}')"
else
    warn "pandoc 未找到 — Word 导出功能将不可用"
    echo ""
    echo "  安装方法:"
    echo "    macOS:  brew install pandoc"
    echo "    Ubuntu: sudo apt install pandoc"
    echo "    Arch:   sudo pacman -S pandoc"
    echo ""
fi

# LaTeX (xelatex + latexmk)
LATEX_CMD="latexmk"
if command -v latexmk &>/dev/null; then
    ok "latexmk ($(which latexmk))"
elif [ -x "/Library/TeX/texbin/latexmk" ]; then
    ok "latexmk (/Library/TeX/texbin/latexmk)"
    LATEX_CMD="/Library/TeX/texbin/latexmk"
else
    warn "latexmk 未找到 — PDF 编译功能将不可用"
    echo ""
    echo "  安装方法:"
    echo "    macOS:  brew install --cask basictex && sudo tlmgr install latexmk"
    echo "    Ubuntu: sudo apt install texlive-xetex texlive-lang-chinese latexmk"
    echo "    Arch:   sudo pacman -S texlive-xetex texlive-langchinese texlive-latexextra"
    echo ""
fi

if command -v xelatex &>/dev/null; then
    ok "xelatex ($(which xelatex))"
elif [ -x "/Library/TeX/texbin/xelatex" ]; then
    ok "xelatex (/Library/TeX/texbin/xelatex)"
else
    warn "xelatex 未找到 — 中文 LaTeX 编译需要此组件"
fi

# LaTeX 宏包 (BasicTeX 精简版需要手动安装常用宏包)
TLMGR=""
if command -v tlmgr &>/dev/null; then
    TLMGR="tlmgr"
elif [ -x "/Library/TeX/texbin/tlmgr" ]; then
    TLMGR="/Library/TeX/texbin/tlmgr"
fi

if [ -n "$TLMGR" ]; then
    LATEX_PACKAGES="enumitem setspace booktabs longtable multirow caption float fancyhdr titlesec tocloft appendix biblatex ctex cjk cjkutils zhnumber latexmk makecell lastpage gensymb xltabular xits placeins algorithmicx algorithms"
    info "检查 LaTeX 宏包..."
    echo "  将安装: $LATEX_PACKAGES"

    # 先尝试 --usermode 安装（公司机器避免 sudo 卡密码），失败再尝试 sudo
    if "$TLMGR" --usermode install $LATEX_PACKAGES 2>/dev/null; then
        ok "LaTeX 宏包安装完成 (usermode)"
    else
        warn "--usermode 安装失败，尝试 sudo 模式..."
        if sudo "$TLMGR" install $LATEX_PACKAGES 2>/dev/null; then
            ok "LaTeX 宏包安装完成"
        else
            warn "部分宏包安装失败，请手动运行: $TLMGR install $LATEX_PACKAGES"
        fi
    fi
fi

if [ ${#MISSING[@]} -gt 0 ]; then
    echo ""
    fail "缺少必要依赖: ${MISSING[*]}"
    echo "  请先安装上述依赖后重新运行此脚本。"
    exit 1
fi

# ------------------------------------------
# 2. 安装 Python 依赖
# ------------------------------------------
echo ""
info "创建 Python 虚拟环境..."

if [ ! -d "$BACKEND_DIR/venv" ]; then
    python3 -m venv "$BACKEND_DIR/venv"
    ok "虚拟环境已创建"
else
    ok "虚拟环境已存在，跳过"
fi

info "安装 Python 依赖..."
source "$BACKEND_DIR/venv/bin/activate"
pip install -q --upgrade pip
pip install -q -r "$BACKEND_DIR/requirements.txt"
ok "Python 依赖安装完成"

# ------------------------------------------
# 3. 安装 Node 依赖 & 构建前端
# ------------------------------------------
echo ""
info "安装前端依赖..."
cd "$FRONTEND_DIR"
npm install --silent 2>/dev/null
ok "前端依赖安装完成"

info "构建前端..."
npm run build
ok "前端构建完成"

# ------------------------------------------
# 4. 配置环境变量
# ------------------------------------------
echo ""
if [ ! -f "$BACKEND_DIR/.env" ]; then
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"

    # Auto-detect latexmk path
    sed -i.bak "s|LATEX_CMD=latexmk|LATEX_CMD=$LATEX_CMD|" "$BACKEND_DIR/.env" && rm -f "$BACKEND_DIR/.env.bak"

    warn ".env 配置文件已创建，请编辑填入 API 密钥:"
    echo ""
    echo "    $BACKEND_DIR/.env"
    echo ""
    echo "  必填项:"
    echo "    DOUBAO_API_KEY=你的豆包API密钥"
    echo "    DOUBAO_MODEL=你的模型端点ID (如 ep-xxxx)"
    echo ""
else
    ok ".env 已存在，跳过"
fi

# ------------------------------------------
# 5. 初始化存储目录
# ------------------------------------------
mkdir -p "$BACKEND_DIR/storage"

# ------------------------------------------
# Done
# ------------------------------------------
echo ""
echo "========================================="
echo -e "  ${GREEN}安装完成!${NC}"
echo ""
echo "  启动服务:"
echo "    ./start.sh"
echo ""
echo "  开发模式 (前后端热更新):"
echo "    ./scripts/dev.sh"
echo ""
echo "  首次使用请先配置 backend/.env"
echo "========================================="
