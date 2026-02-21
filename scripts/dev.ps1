# =========================================
#  Smart-LaTeX 开发模式脚本 (Windows PowerShell)
# =========================================

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendDir = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"

Write-Host "========================================="
Write-Host "  Smart-LaTeX Development Server"
Write-Host "========================================="

# Check venv
$VenvDir = Join-Path $BackendDir "venv"
if (-not (Test-Path $VenvDir)) {
    Write-Host "[ERROR] Python venv not found. Run .\install.ps1 first." -ForegroundColor Red
    exit 1
}

# Activate venv
$ActivateScript = Join-Path $VenvDir "Scripts\Activate.ps1"
& $ActivateScript

# Start backend
Write-Host ""
Write-Host "Starting backend server..."
$BackendJob = Start-Job -ScriptBlock {
    param($dir, $activate)
    & $activate
    Set-Location $dir
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
} -ArgumentList $BackendDir, $ActivateScript

Write-Host "  Backend Job ID: $($BackendJob.Id)"

# Start frontend
Write-Host ""
Write-Host "Starting frontend dev server..."
$FrontendJob = Start-Job -ScriptBlock {
    param($dir)
    Set-Location $dir
    npm run dev -- --host 0.0.0.0 --port 5173
} -ArgumentList $FrontendDir

Write-Host "  Frontend Job ID: $($FrontendJob.Id)"

# Print access URLs
Write-Host ""
Write-Host "========================================="
Write-Host "  Services running:"
Write-Host ""
Write-Host "  Frontend:  http://localhost:5173"
Write-Host "  Backend:   http://localhost:8000"
Write-Host "  API Docs:  http://localhost:8000/docs"
Write-Host ""
Write-Host "  Press Ctrl+C to stop all services"
Write-Host "========================================="

# Cleanup on exit
try {
    # Wait and stream output
    while ($true) {
        # Check if jobs are still running
        $backendState = (Get-Job -Id $BackendJob.Id).State
        $frontendState = (Get-Job -Id $FrontendJob.Id).State

        # Receive and display output
        Receive-Job -Job $BackendJob -ErrorAction SilentlyContinue
        Receive-Job -Job $FrontendJob -ErrorAction SilentlyContinue

        if ($backendState -eq "Failed" -or $frontendState -eq "Failed") {
            Write-Host "A service has stopped unexpectedly." -ForegroundColor Red
            break
        }

        Start-Sleep -Milliseconds 500
    }
} finally {
    Write-Host ""
    Write-Host "Shutting down..."
    Stop-Job -Job $BackendJob -ErrorAction SilentlyContinue
    Stop-Job -Job $FrontendJob -ErrorAction SilentlyContinue
    Remove-Job -Job $BackendJob -ErrorAction SilentlyContinue
    Remove-Job -Job $FrontendJob -ErrorAction SilentlyContinue
    Write-Host "  All services stopped."
}
