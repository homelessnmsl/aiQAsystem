#Requires -Version 5.1
<#
.SYNOPSIS
  企业知识库智能问答系统 · 一键演示启动（W4-02 / W4-06）
.DESCRIPTION
  一条命令启动演示环境：后端(FastAPI) + 前端(Streamlit)，自动等待健康检查、
  执行一次检索预热（加载本地向量模型），并把日志写入 data\logs\demo\。
  进程 PID 记录于 data\logs\demo\pids.json，可用 -Stop 一键停止。
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\start_demo.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\start_demo.ps1 -Stop
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\start_demo.ps1 -ForceRestart
#>
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 8501,
    [switch]$SkipWarmup,
    [switch]$NoBrowser,
    [switch]$ForceRestart,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $Root "data\logs\demo"
$PidFile = Join-Path $LogDir "pids.json"
$BackendBase = "http://127.0.0.1:$BackendPort"
$FrontendUrl = "http://localhost:$FrontendPort"

function Write-Step([string]$Text) { Write-Host "[演示启动] $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text)   { Write-Host "  √ $Text" -ForegroundColor Green }
function Write-Warn([string]$Text) { Write-Host "  ！$Text" -ForegroundColor Yellow }
function Write-Err([string]$Text)  { Write-Host "  × $Text" -ForegroundColor Red }

function Test-Port([int]$Port) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok = $async.AsyncWaitHandle.WaitOne(500)
        $client.Close()
        return $ok
    } catch { return $false }
}

function Get-PidRecord() {
    if (-not (Test-Path $PidFile)) { return $null }
    try { return (Get-Content $PidFile -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { return $null }
}

# ============================================================
# -Stop：停止本脚本启动的服务
# ============================================================
if ($Stop) {
    $record = Get-PidRecord
    if (-not $record) { Write-Warn "未找到 PID 记录（$PidFile），未通过本脚本启动过服务？"; exit 0 }
    foreach ($name in @("backend", "frontend")) {
        $procId = $record.$name
        if ($procId) {
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($proc) {
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                Write-Ok "已停止 $name（PID $procId）"
            } else {
                Write-Warn "$name（PID $procId）已不在运行"
            }
        }
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    exit 0
}

# ============================================================
# 0) 环境检查
# ============================================================
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (-not (Test-Path $Python)) {
    Write-Err "未找到虚拟环境：$Python"
    Write-Host "  请先在仓库根目录执行：python -m venv .venv"
    Write-Host "  然后执行：.venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}
if (-not (Test-Path (Join-Path $Root ".env"))) {
    Write-Warn "未找到 .env —— 问答接口将返回 3003；请复制 .env.example 为 .env 并填入 DEEPSEEK_API_KEY"
}

$backendPid = $null
$frontendPid = $null

# ============================================================
# 1) 后端（FastAPI / uvicorn）
# ============================================================
if ((Test-Port $BackendPort) -and $ForceRestart) {
    $record = Get-PidRecord
    if ($record -and $record.backend) {
        Write-Step "重启后端（停止 PID $($record.backend)）"
        Stop-Process -Id $record.backend -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    } else {
        Write-Err "端口 $BackendPort 被其它进程占用，且非本脚本启动（无 PID 记录）。请手动结束该进程后重试。"
        exit 1
    }
}

if (Test-Port $BackendPort) {
    Write-Warn "后端端口 $BackendPort 已在监听，复用现有服务"
    Write-Warn "若该进程启动于本次代码更新之前（可能缺少新接口），请先结束它再运行本脚本"
} else {
    Write-Step "启动后端：python -m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort"
    $backendProcess = Start-Process -FilePath $Python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort") `
        -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $LogDir "backend.out.log") `
        -RedirectStandardError (Join-Path $LogDir "backend.err.log")
    $backendPid = $backendProcess.Id
    Write-Ok "后端进程已启动（PID $backendPid）"
}

# ============================================================
# 2) 等待健康检查（最多 60 秒）
# ============================================================
Write-Step "等待后端就绪：$BackendBase/api/health"
$health = $null
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Method Get -Uri "$BackendBase/api/health" -TimeoutSec 5
        if ($health.code -eq 0) { break }
    } catch { $health = $null }
    Start-Sleep -Milliseconds 800
}
if (-not $health -or $health.code -ne 0) {
    Write-Err "后端 60 秒内未就绪，请查看日志：$LogDir\backend.err.log"
    exit 1
}

$deps = $health.data.dependencies
Write-Ok ("健康检查通过：status={0}｜llm={1}｜向量库={2}（{3} 切片）｜台账={4} 文档" -f `
    $health.data.status, $deps.llm.status, $deps.vector_store.status, $deps.vector_store.chunk_count, $deps.sqlite.documents)
if ($deps.llm.status -ne "ok") { Write-Warn "LLM 未配置：/api/ask 将返回 3003，请检查 .env" }
if ($deps.vector_store.chunk_count -eq 0) {
    Write-Warn "知识库为空：可运行 python scripts/init_kb.py 导入样例文档（或在页面中上传）；本次跳过预热"
    $SkipWarmup = $true
}

# ============================================================
# 3) 检索预热（首次请求会加载本地向量模型，约 10~15 秒）
# ============================================================
if (-not $SkipWarmup) {
    Write-Step "执行一次检索预热（加载本地向量模型，约 10~15 秒，请稍候）"
    $t0 = Get-Date
    try {
        $body = [System.Text.Encoding]::UTF8.GetBytes('{"question":"公司的标准工作时间是几点到几点？"}')
        $warm = Invoke-RestMethod -Method Post -Uri "$BackendBase/api/ask" `
            -ContentType "application/json; charset=utf-8" -Body $body -TimeoutSec 120
        $elapsed = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
        Write-Ok "预热完成（$elapsed 秒）：answer_type=$($warm.data.answer_type)"
    } catch {
        Write-Warn "预热失败（不影响启动，可稍后在页面重试）：$($_.Exception.Message)"
    }
}

# ============================================================
# 4) 前端（Streamlit）
# ============================================================
if (Test-Port $FrontendPort) {
    Write-Warn "前端端口 $FrontendPort 已在监听，复用现有服务"
} else {
    Write-Step "启动前端：streamlit run web/app.py --server.port $FrontendPort"
    $env:WEB_API_BASE = $BackendBase
    $frontendProcess = Start-Process -FilePath $Python `
        -ArgumentList @("-m", "streamlit", "run", "web/app.py", "--server.port", "$FrontendPort",
                        "--server.headless", "true", "--browser.gatherUsageStats", "false") `
        -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $LogDir "frontend.out.log") `
        -RedirectStandardError (Join-Path $LogDir "frontend.err.log")
    $frontendPid = $frontendProcess.Id
    Write-Ok "前端进程已启动（PID $frontendPid）"

    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline -and -not (Test-Port $FrontendPort)) { Start-Sleep -Milliseconds 800 }
    if (Test-Port $FrontendPort) { Write-Ok "前端就绪：$FrontendUrl" }
    else { Write-Warn "前端 60 秒内未就绪，请查看日志：$LogDir\frontend.err.log" }
}

# ============================================================
# 5) 记录 PID（合并复用中的既有记录）
# ============================================================
$record = Get-PidRecord
if ($record) {
    if (-not $backendPid -and $record.backend)  { $backendPid = $record.backend }
    if (-not $frontendPid -and $record.frontend) { $frontendPid = $record.frontend }
}
$state = [ordered]@{
    backend       = $backendPid
    frontend      = $frontendPid
    backend_port  = $BackendPort
    frontend_port = $FrontendPort
}
[System.IO.File]::WriteAllText($PidFile, ($state | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))

# ============================================================
# 6) 汇总
# ============================================================
Write-Host ""
Write-Host "================ 演示环境就绪 ================" -ForegroundColor Green
Write-Host ("  问答页（演示入口）：{0}" -f $FrontendUrl)
Write-Host ("  后端 Swagger：      {0}/docs" -f $BackendBase)
Write-Host ("  健康检查：          {0}/api/health" -f $BackendBase)
Write-Host ("  日志目录：          {0}" -f $LogDir)
Write-Host  "  停止服务：          powershell -ExecutionPolicy Bypass -File scripts\start_demo.ps1 -Stop"
Write-Host "==============================================" -ForegroundColor Green

if (-not $NoBrowser) { Start-Process $FrontendUrl | Out-Null }
