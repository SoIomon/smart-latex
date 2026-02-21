# =========================================
#  Smart-LaTeX 启动脚本 (Windows PowerShell)
# =========================================

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $ProjectRoot "backend"
$FrontendDist = Join-Path $ProjectRoot "frontend\dist"
$Port = if ($env:PORT) { $env:PORT } else { "8000" }

# Check venv
$VenvDir = Join-Path $BackendDir "venv"
if (-not (Test-Path $VenvDir)) {
    Write-Host "[ERROR] 未找到虚拟环境，请先运行: .\install.ps1" -ForegroundColor Red
    exit 1
}

# Check .env
$EnvFile = Join-Path $BackendDir ".env"
if (-not (Test-Path $EnvFile)) {
    Write-Host "[ERROR] 未找到配置文件，请先运行: .\install.ps1" -ForegroundColor Red
    exit 1
}

# Check frontend build
if (-not (Test-Path $FrontendDist)) {
    Write-Host "[WARN] 前端未构建，正在构建..." -ForegroundColor Yellow
    Push-Location (Join-Path $ProjectRoot "frontend")
    npm run build
    Pop-Location
}

# Activate venv
$ActivateScript = Join-Path $VenvDir "Scripts\Activate.ps1"
& $ActivateScript

Write-Host ""
Write-Host "========================================="
Write-Host "  Smart-LaTeX 正在启动..." -ForegroundColor Green
Write-Host ""
Write-Host "  访问地址: http://localhost:$Port"
Write-Host "  API 文档: http://localhost:$Port/docs"
Write-Host ""
Write-Host "  按 Ctrl+C 停止服务"
Write-Host "========================================="
Write-Host ""

Push-Location $BackendDir
uvicorn app.main:app --host 0.0.0.0 --port $Port
Pop-Location
