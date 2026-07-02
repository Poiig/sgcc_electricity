# Local Web dashboard (reads DB config from project root .env)
# Ctrl+C 直接传给 Python 子进程，uvicorn 优雅退出(timeout_graceful_shutdown=3)，
# 不拦截信号，避免退出慢 / 终端卡死。
$ErrorActionPreference = "Stop"
$DevDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $DevDir
$ReqFile = Join-Path $DevDir "requirements-dashboard.txt"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

function Get-DashboardPort {
    param([string]$EnvPath)
    $port = 8080
    if (Test-Path $EnvPath) {
        Get-Content $EnvPath -Encoding UTF8 | ForEach-Object {
            if ($_ -match '^\s*WEB_DASHBOARD_PORT\s*=\s*"?(\d+)"?\s*$') {
                $script:port = [int]$Matches[1]
            }
        }
    }
    return $port
}

function Stop-ListenPort {
    param([int]$Port)
    $killed = $false
    netstat -ano | Select-String ":\s*$Port\s+.*LISTENING" | ForEach-Object {
        $procId = ($_.Line.Trim() -split '\s+')[-1]
        if ($procId -match '^\d+$' -and [int]$procId -gt 0) {
            Write-Host "[INFO] 端口 $Port 被 PID $procId 占用，正在停止..." -ForegroundColor Yellow
            Stop-Process -Id ([int]$procId) -Force -ErrorAction SilentlyContinue
            $killed = $true
        }
    }
    if ($killed) { Start-Sleep -Milliseconds 500 }
}

if (-not (Test-Path (Join-Path $Root ".env"))) {
    Write-Host "[提示] 未找到 .env，可执行：copy example.env .env" -ForegroundColor Yellow
}

$Port = Get-DashboardPort -EnvPath (Join-Path $Root ".env")
Stop-ListenPort -Port $Port

if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = "python"
}

& $Python -c "import fastapi" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[INFO] 安装控制台依赖：$ReqFile" -ForegroundColor Cyan
    & $Python -m pip install -r $ReqFile
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[错误] pip install 失败" -ForegroundColor Red
        exit 1
    }
}

$env:PYTHONUNBUFFERED = "1"

# Push-Location 进入 scripts 目录，finally 里 Pop-Location 回到原目录，
# 确保 Ctrl+C 退出后提示符回到调用脚本时的位置(dev/)而非 scripts/。
Push-Location (Join-Path $Root "scripts")
try {
    # 前台调用：Ctrl+C 直接传给 Python，uvicorn 在 timeout_graceful_shutdown(3s)内退出
    & $Python -u run_dashboard.py
} catch {
    # Ctrl+C 在某些 PowerShell 版本会抛异常，正常忽略
} finally {
    # 无论正常退出还是 Ctrl+C，都恢复原工作目录
    Pop-Location -ErrorAction SilentlyContinue
}
