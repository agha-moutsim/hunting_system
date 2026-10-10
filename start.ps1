<#
.SYNOPSIS
  Start the eBay Hunter backend and frontend as detached background processes.

.DESCRIPTION
  Both servers are LONG-RUNNING BY DESIGN. `next start` and `uvicorn` never
  exit — that is a healthy server, not a stuck command. This script launches
  them detached so they survive the shell that started them, then verifies
  they are actually serving.

  The redirection is placed INSIDE the child command line on purpose. Using
  Start-Process -RedirectStandardOutput/Error on this host causes the parent
  to block indefinitely — that is the behaviour that looks like "the command
  never finishes".

.EXAMPLE
  .\start.ps1
#>
[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [int]$WaitSeconds = 25
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $Root '.logs'
$BackendDir = Join-Path $Root 'backend'

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Test-PortListening {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Get-ListenerPid {
    param([int]$Port)
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return $c.OwningProcess }
    return $null
}

Write-Host ''
Write-Host '  eBay Hunter' -ForegroundColor Cyan
Write-Host '  -----------' -ForegroundColor DarkCyan
Write-Host ''

foreach ($p in @($BackendPort, $FrontendPort)) {
    if (Test-PortListening $p) {
        $existing = Get-ListenerPid $p
        Write-Host "  port $p already in use (pid $existing)." -ForegroundColor Yellow
        Write-Host "  Run .\stop.ps1 first." -ForegroundColor Yellow
        Write-Host ''
        return
    }
}

# --- backend -------------------------------------------------------------
# `cmd /c "... > log 2> log.err"` keeps the redirect inside the child, so the
# parent never waits on a file handle.
$beOut = Join-Path $LogDir 'backend.log'
$beErr = Join-Path $LogDir 'backend.err.log'
$beCmd = "python -m uvicorn main:app --host 127.0.0.1 --port $BackendPort > `"$beOut`" 2> `"$beErr`""
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $beCmd `
    -WorkingDirectory $BackendDir -WindowStyle Hidden | Out-Null
Write-Host "  backend  starting on :$BackendPort ..." -ForegroundColor DarkGray

# --- frontend ------------------------------------------------------------
$feOut = Join-Path $LogDir 'frontend.log'
$feErr = Join-Path $LogDir 'frontend.err.log'
$feCmd = "npm --prefix frontend run start > `"$feOut`" 2> `"$feErr`""
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $feCmd `
    -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
Write-Host "  frontend starting on :$FrontendPort ..." -ForegroundColor DarkGray

Write-Host ''
Write-Host "  waiting up to $WaitSeconds seconds ..." -ForegroundColor DarkGray
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$backendOk = $false
$frontendOk = $false

while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    if (-not $backendOk -and (Test-PortListening $BackendPort)) { $backendOk = $true }
    if (-not $frontendOk -and (Test-PortListening $FrontendPort)) { $frontendOk = $true }
    if ($backendOk -and $frontendOk) { break }
}

# --- verify --------------------------------------------------------------
Write-Host ''
$exitCode = 0

if ($backendOk) {
    $pid1 = Get-ListenerPid $BackendPort
    Write-Host "  backend   UP   http://127.0.0.1:$BackendPort   (pid $pid1)" -ForegroundColor Green
} else {
    Write-Host "  backend   FAILED to bind :$BackendPort" -ForegroundColor Red
    if (Test-Path $beErr) { Get-Content $beErr -Tail 8 | ForEach-Object { Write-Host "            $_" -ForegroundColor DarkRed } }
    $exitCode = 1
}

if ($frontendOk) {
    $pid2 = Get-ListenerPid $FrontendPort
    Write-Host "  frontend  UP   http://localhost:$FrontendPort   (pid $pid2)" -ForegroundColor Green
} else {
    Write-Host "  frontend  FAILED to bind :$FrontendPort" -ForegroundColor Red
    if (Test-Path $feErr) { Get-Content $feErr -Tail 8 | ForEach-Object { Write-Host "            $_" -ForegroundColor DarkRed } }
    $exitCode = 1
}

Write-Host ''
Write-Host ("  Open   http://localhost:{0}" -f $FrontendPort) -ForegroundColor Cyan
Write-Host ("  Health http://127.0.0.1:{0}/api/health" -f $BackendPort) -ForegroundColor Cyan
Write-Host ("  Logs   {0}" -f $LogDir) -ForegroundColor DarkGray
Write-Host '  Stop   .\stop.ps1' -ForegroundColor DarkGray
Write-Host ''

exit $exitCode