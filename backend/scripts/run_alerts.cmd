@echo off
REM One alerts pass, for Windows Task Scheduler.
REM
REM Mirrors run_demand_monitor.cmd: the repository path contains a space
REM ("Agha Moutsim"), so the task points at this file rather than at a
REM python command line (see schedule_alerts.xml for why registration goes
REM through XML). Both the working directory and the log path are derived
REM from %~dp0, and deliberately NOT relative to the current directory: run
REM by hand it works either way, but Task Scheduler starts the process in
REM its own working directory, where a relative "data\..." would land
REM somewhere unwritable and the job would fail with no log and no
REM explanation. An absolute path derived from the script's own location
REM cannot drift.
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

python -m scripts.run_alerts >> "%~dp0..\data\alerts.log" 2>&1
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
