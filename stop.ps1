<#
.SYNOPSIS
  Stop the eBay Hunter backend and frontend, including their process trees.

.DESCRIPTION
  Killing only the direct child is what leaks processes on this host: a
  `next start` spawns a Node child that survives its parent, and `uvicorn`
  under `cmd /c` behaves the same way. This script kills each listener AND its
  descendants, then verifies nothing is still bound.

.EXAMPLE
  .\stop.ps1
#>
[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000
)

$ErrorActionPreference = 'SilentlyContinue'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $Root '.logs'

function Get-ListenerPid {
    param([int]$Port)
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen | Select-Object -First 1
    if ($c) { return $c.OwningProcess }
    return $null
}

function Get-DescendantPids {
    param([int]$ParentPid)
    $all = Get-CimInstance Win32_Process
    $result = New-Object System.Collections.Generic.List[int]
    $queue = New-Object System.Collections.Generic.Queue[int]
    $queue.Enqueue($ParentPid)
    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        foreach ($child in $all | Where-Object { $_.ParentProcessId -eq $current }) {
            if (-not $result.Contains([int]$child.ProcessId)) {
                $result.Add([int]$child.ProcessId)
                $queue.Enqueue([int]$child.ProcessId)
            }
        }
    }
    return $result
}

function Stop-Tree {
    param([int]$Pid_, [string]$Label)

    $children = Get-DescendantPids -ParentPid $Pid_
    if ($children.Count -gt 0) {
        Write-Host "  $Label : stopping $($children.Count) child process(es)" -ForegroundColor DarkGray
        foreach ($c in $children) { Stop-Process -Id $c -Force }
    }
    Stop-Process -Id $Pid_ -Force
    Write-Host "  $Label : stopped (pid $Pid_)" -ForegroundColor Green
}

Write-Host ''
Write-Host '  Stopping eBay Hunter' -ForegroundColor Cyan
Write-Host ''

foreach ($target in @(@{ Port = $FrontendPort; Label = 'frontend' },
                      @{ Port = $BackendPort;  Label = 'backend' })) {
    $pid_ = Get-ListenerPid -Port $target.Port
    if ($pid_) {
        Stop-Tree -Pid_ $pid_ -Label $target.Label
    } else {
        Write-Host "  $($target.Label) : nothing listening on :$($target.Port)" -ForegroundColor DarkGray
    }
}

Start-Sleep -Seconds 2

Write-Host ''
$stillUp = $false
foreach ($target in @(@{ Port = $FrontendPort; Label = 'frontend' },
                      @{ Port = $BackendPort;  Label = 'backend' })) {
    if (Get-ListenerPid -Port $target.Port) {
        Write-Host "  $($target.Label) : STILL LISTENING on :$($target.Port)" -ForegroundColor Red
        $stillUp = $true
    } else {
        Write-Host "  $($target.Label) : stopped" -ForegroundColor DarkGray
    }
}

if ($stillUp) { exit 1 }
Write-Host ''
exit 0