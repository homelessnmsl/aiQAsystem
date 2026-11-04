#Requires -Version 5.1
<#
.SYNOPSIS
  aiQAsystem · Gitee/GitHub 双仓库自动同步（PM 工具）
.DESCRIPTION
  把本仓库全部分支与标签推送到 Gitee 与 GitHub 两个远端。
  - Gitee 认证：Windows 凭据管理器（已有）
  - GitHub 认证：.github_token 文件（已被 .gitignore 忽略）或 GITHUB_TOKEN 环境变量
  - GitHub 走本机 7897 代理（仓库级 git 配置 http.https://github.com/.proxy）
  - 定时任务：aiQAsystem-双仓库同步（每天 12:30，schtasks /Delete /TN "aiQAsystem-双仓库同步" /F 可删除）
#>
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$LogFile = Join-Path $Root "data\logs\sync_remotes.log"

function Write-Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Output $line
}

$token = $env:GITHUB_TOKEN
if (-not $token) {
    $tokenFile = Join-Path $Root ".github_token"
    if (Test-Path $tokenFile) { $token = (Get-Content $tokenFile -Raw).Trim() }
}
if (-not $token) { Write-Log "[ERROR] no GitHub token (GITHUB_TOKEN or .github_token)"; exit 1 }

if (-not (git config --get http.https://github.com/.proxy)) {
    git config http.https://github.com/.proxy socks5h://127.0.0.1:7897
}

$gh = "https://homelessnmsl:$token@github.com/homelessnmsl/aiQAsystem.git"
$refs = @("refs/heads/*:refs/heads/*", "refs/tags/*:refs/tags/*")

Write-Log "==== sync start ===="
foreach ($ref in $refs) {
    $msg1 = (cmd /c "git push origin $ref 2>&1" | Out-String).Trim().Replace("`r`n", " | ")
    Write-Log "[Gitee $ref] $msg1"
    $msg2 = (cmd /c "git push $gh $ref 2>&1" | Out-String).Trim().Replace("`r`n", " | ")
    Write-Log "[GitHub $ref] $msg2"
}
Write-Log "==== sync done ===="


