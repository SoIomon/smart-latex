# =========================================
#  Smart-LaTeX 一键安装脚本 (Windows PowerShell)
#  v1.0.0
# =========================================

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"

function Write-Info  { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Blue }
function Write-Ok    { param($msg) Write-Host "[OK]   $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Fail  { param($msg) Write-Host "[FAIL] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "========================================="
Write-Host "  Smart-LaTeX 一键安装 v1.0.0 (Windows)"
Write-Host "========================================="
Write-Host ""

# ------------------------------------------
# 1. 检查系统依赖
# ------------------------------------------
Write-Info "检查系统依赖..."

$Missing = @()

# Python 3.10+
$PythonCmd = $null
foreach ($cmd in @("python3", "python")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $PythonCmd = $cmd
        break
    }
}

if ($PythonCmd) {
    $PyVer = & $PythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    $PyMajor, $PyMinor = $PyVer.Split('.')
    if ([int]$PyMajor -ge 3 -and [int]$PyMinor -ge 10) {
        Write-Ok "Python $PyVer ($PythonCmd)"
    } else {
        Write-Fail "Python $PyVer (需要 3.10+)"
        $Missing += "python3.10+"
    }
} else {
    Write-Fail "Python 未安装"
    Write-Host "  安装方法: winget install Python.Python.3.12"
    $Missing += "python"
}

# Node.js 18+
if (Get-Command node -ErrorAction SilentlyContinue) {
    $NodeVer = (node -v).TrimStart('v')
    $NodeMajor = [int]($NodeVer.Split('.')[0])
    if ($NodeMajor -ge 18) {
        Write-Ok "Node.js $NodeVer"
    } else {
        Write-Fail "Node.js $NodeVer (需要 18+)"
        $Missing += "node18+"
    }
} else {
    Write-Fail "Node.js 未安装"
    Write-Host "  安装方法: winget install OpenJS.NodeJS.LTS"
    $Missing += "node"
}

# npm
if (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Ok "npm $(npm -v)"
} else {
    Write-Fail "npm 未安装 (通常随 Node.js 一起安装)"
    $Missing += "npm"
}

# Pandoc
if (Get-Command pandoc -ErrorAction SilentlyContinue) {
    $PandocVer = (pandoc --version | Select-Object -First 1).Split(' ')[-1]
    Write-Ok "pandoc $PandocVer"
} else {
    Write-Warn "pandoc 未找到 - Word 导出功能将不可用"
    Write-Host "  安装方法: winget install JohnMacFarlane.Pandoc"
}

# LaTeX (xelatex + latexmk)
$HasXelatex = $false
$HasLatexmk = $false

if (Get-Command xelatex -ErrorAction SilentlyContinue) {
    Write-Ok "xelatex ($((Get-Command xelatex).Source))"
    $HasXelatex = $true
} else {
    Write-Warn "xelatex 未找到 - 中文 LaTeX 编译需要此组件"
}

if (Get-Command latexmk -ErrorAction SilentlyContinue) {
    Write-Ok "latexmk ($((Get-Command latexmk).Source))"
    $HasLatexmk = $true
} else {
    Write-Warn "latexmk 未找到 - PDF 编译功能将不可用"
}

if (-not $HasXelatex -or -not $HasLatexmk) {
    Write-Host ""
    Write-Host "  LaTeX 安装方法 (任选其一):"
    Write-Host "    MiKTeX:   winget install MiKTeX.MiKTeX  (推荐，自动安装宏包)"
    Write-Host "    TeX Live: https://tug.org/texlive/"
    Write-Host ""
}

if ($Missing.Count -gt 0) {
    Write-Host ""
    Write-Fail "缺少必要依赖: $($Missing -join ', ')"
    Write-Host "  请先安装上述依赖后重新运行此脚本。"
    exit 1
}

# ------------------------------------------
# 2. 安装 Python 依赖
# ------------------------------------------
Write-Host ""
Write-Info "创建 Python 虚拟环境..."

$VenvDir = Join-Path $BackendDir "venv"
if (-not (Test-Path $VenvDir)) {
    & $PythonCmd -m venv $VenvDir
    Write-Ok "虚拟环境已创建"
} else {
    Write-Ok "虚拟环境已存在，跳过"
}

Write-Info "安装 Python 依赖..."
$PipExe = Join-Path $VenvDir "Scripts\pip.exe"
& $PipExe install -q --upgrade pip
& $PipExe install -q -r (Join-Path $BackendDir "requirements.txt")
Write-Ok "Python 依赖安装完成"

# ------------------------------------------
# 3. 安装 Node 依赖 & 构建前端
# ------------------------------------------
Write-Host ""
Write-Info "安装前端依赖..."
Push-Location $FrontendDir
npm install --silent 2>$null
Write-Ok "前端依赖安装完成"

Write-Info "构建前端..."
npm run build
Write-Ok "前端构建完成"
Pop-Location

# ------------------------------------------
# 4. 配置环境变量
# ------------------------------------------
Write-Host ""
$EnvFile = Join-Path $BackendDir ".env"
$EnvExample = Join-Path $BackendDir ".env.example"

if (-not (Test-Path $EnvFile)) {
    Copy-Item $EnvExample $EnvFile
    Write-Warn ".env 配置文件已创建，请编辑填入 API 密钥:"
    Write-Host ""
    Write-Host "    $EnvFile"
    Write-Host ""
    Write-Host "  必填项:"
    Write-Host "    DOUBAO_API_KEY=你的豆包API密钥"
    Write-Host "    DOUBAO_MODEL=你的模型端点ID (如 ep-xxxx)"
    Write-Host ""
} else {
    Write-Ok ".env 已存在，跳过"
}

# ------------------------------------------
# 5. 初始化存储目录
# ------------------------------------------
$StorageDir = Join-Path $BackendDir "storage"
if (-not (Test-Path $StorageDir)) {
    New-Item -ItemType Directory -Path $StorageDir -Force | Out-Null
}

# ------------------------------------------
# Done
# ------------------------------------------
Write-Host ""
Write-Host "========================================="
Write-Host "  安装完成!" -ForegroundColor Green
Write-Host ""
Write-Host "  启动服务:"
Write-Host "    .\start.ps1"
Write-Host ""
Write-Host "  开发模式 (前后端热更新):"
Write-Host "    .\scripts\dev.ps1"
Write-Host ""
Write-Host "  首次使用请先配置 backend\.env"
Write-Host "========================================="
