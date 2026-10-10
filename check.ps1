<#
.SYNOPSIS
  Report whether the backend and frontend are actually serving.

.DESCRIPTION
  Answers the question that "the command never finishes" left ambiguous:
  a long-running server is healthy, and this proves it by making a real
  request rather than by inspecting whether a process exists.

  Exit code 0 = both healthy, 1 = something is wrong.

.EXAMPLE
  .\check.ps1
#>
[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [switch]$Quiet
)

$ErrorActionPreference = 'SilentlyContinue'

function Get-Health {
    param([string]$Name, [string]$Url)

    try {
        $r = Invoke-WebRequest -Uri $Url -TimeoutSec 15 -UseBasicParsing
        return [pscustomobject]@{
            Name = $Name; Url = $Url; Ok = ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400)
            Status = $r.StatusCode; Detail = ''
        }
    } catch {
        $msg = $_.Exception.Message
        return [pscustomobject]@{
            Name = $Name; Url = $Url; Ok = $false; Status = 0; Detail = $msg
        }
    }
}

function Get-PortState {
    param([int]$Port)
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen | Select-Object -First 1
    if ($c) { return "pid $($c.OwningProcess)" }
    return 'not listening'
}

$checks = @(
    Get-Health -Name 'backend ' -Url "http://127.0.0.1:$BackendPort/api/health"
    Get-Health -Name 'frontend' -Url "http://localhost:$FrontendPort"
)

if (-not $Quiet) {
    Write-Host ''
    Write-Host '  eBay Hunter status' -ForegroundColor Cyan
    Write-Host '  -------------------' -ForegroundColor DarkCyan
    Write-Host ''
    Write-Host ("  backend  :{0,-6} {1}" -f $BackendPort, (Get-PortState $BackendPort)) -ForegroundColor DarkGray
    Write-Host ("  frontend :{0,-6} {1}" -f $FrontendPort, (Get-PortState $FrontendPort)) -ForegroundColor DarkGray
    Write-Host ''
}

$allOk = $true
foreach ($c in $checks) {
    if ($c.Ok) {
        if (-not $Quiet) {
            Write-Host ("  {0}  UP    HTTP {1}  {2}" -f $c.Name, $c.Status, $c.Url) -ForegroundColor Green
        }
    } else {
        $allOk = $false
        if (-not $Quiet) {
            Write-Host ("  {0}  DOWN  {1}" -f $c.Name, $c.Detail) -ForegroundColor Red
        }
    }
}

if (-not $Quiet) {
    Write-Host ''
    if ($allOk) {
        Write-Host '  Both services are serving requests.' -ForegroundColor Green
    } else {
        Write-Host '  At least one service is NOT responding. Start with .\start.ps1' -ForegroundColor Yellow
    }
    Write-Host ''
}

if ($allOk) { exit 0 }
exit 1