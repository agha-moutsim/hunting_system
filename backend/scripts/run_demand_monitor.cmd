@echo off
REM One demand-monitor pass, for Windows Task Scheduler.
REM
REM This wrapper exists because the repository path contains a space
REM ("Agha Moutsim"), and schtasks.exe /tr takes a single command string - so
REM nesting cmd.exe quotes inside it is a quoting nightmare. Pointing the task
REM at this file means the task's command is just a path.
REM
REM Both the working directory and the log path are derived from %~dp0, and
REM deliberately NOT relative to the current directory: run by hand it works
REM either way, but Task Scheduler starts the process in its own working
REM directory, where a relative "data\..." would land somewhere unwritable and
REM the job would fail with no log and no explanation. An absolute path derived
REM from the script's own location cannot drift.
REM
REM pushd rather than cd /d, so a mapped or UNC repo path also works.
REM
REM Output is appended, never overwritten, so each run's result is kept. The
REM log is gitignored (*.log).

pushd "%~dp0.." 2>nul
if errorlevel 1 (
    echo [%DATE% %TIME%] could not enter %~dp0.. - aborting
    exit /b 1
)

python -m scripts.run_demand_monitor >> "%~dp0..\data\demand_monitor.log" 2>&1
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%