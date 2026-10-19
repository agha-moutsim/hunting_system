"""The alerts pass must actually run unattended.

An alert that only exists when someone opens a page is a report, not an
alert. So the scheduled task is verified against the OS rather than assumed
from a command's exit code - the same reasoning (and the same hard-won
registration recipe) as test_demand_monitor_schedule.py.

What that file found on this machine, which shapes these checks:

  * `Import-ScheduledTask` is unavailable - the ScheduledTasks module's
    manifest is present but its native DLL is not, so every cmdlet in it is
    missing. Registration goes through schtasks.exe + an XML file converted
    to real UTF-16 ("unable to switch the encoding" otherwise).
  * `schtasks.exe /create /tr "<path with spaces>"` silently splits at the
    first space: the task registers with `C:\\Users\\Agha` as the executable
    and fails every run with 0x80070002, with no log. XML cannot split it.

The OS-facing tests skip when the task is not registered, so the suite still
runs on another machine or in CI.
"""

import re
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
SCRIPTS = BACKEND / "scripts"
CMD = SCRIPTS / "run_alerts.cmd"
TASK_NAME = "eBayHunter Alerts"


def _schtasks(*args):
    try:
        out = subprocess.run(
            ["schtasks.exe", *args], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout + out.stderr


@pytest.fixture(scope="module")
def registered_task_xml():
    out = _schtasks("/query", "/tn", TASK_NAME, "/xml")
    if not out or "ERROR:" in out or "<Task" not in out:
        pytest.skip(f"{TASK_NAME} is not registered on this machine")
    return out


class TestTheBatchWrapperIsRelocatable:
    def test_it_exists(self):
        assert CMD.exists(), "the scheduled task points at this file"

    def test_it_derives_paths_from_its_own_location(self):
        """A hardcoded absolute path would silently break the moment the repo
        moves, and the task would keep failing every hour with no log."""
        text = CMD.read_text(encoding="utf-8")
        assert "%~dp0" in text
        assert not re.search(r"[A-Za-z]:\\\\?Users", text, re.I)

    def test_the_log_path_is_absolute_not_relative(self):
        text = CMD.read_text(encoding="utf-8")
        assert re.search(r'>>\s*"%~dp0', text), (
            "the log redirect must be derived from %~dp0, not from the "
            "current directory"
        )

    def test_it_changes_directory_before_running(self):
        """`python -m scripts.run_alerts` only resolves from backend/."""
        text = CMD.read_text(encoding="utf-8")
        assert 'pushd "%~dp0.."' in text

    def test_it_appends_rather_than_overwrites_the_log(self):
        text = CMD.read_text(encoding="utf-8")
        assert re.search(r'>>\s*"%~dp0\.\.[\\/]data[\\/]alerts\.log"', text)
        assert not re.search(r"(?<![>0-9])>\s*\"%~dp0", text), (
            "the log is being overwritten rather than appended"
        )

    def test_it_propagates_the_exit_code(self):
        text = CMD.read_text(encoding="utf-8").lower()
        assert "exit /b %rc%" in text

    def test_the_log_is_gitignored(self):
        gitignore = (BACKEND.parent / ".gitignore").read_text(encoding="utf-8")
        assert "*.log" in gitignore

    def test_the_python_module_it_calls_exists(self):
        assert (SCRIPTS / "run_alerts.py").exists()

    def test_it_runs_the_alerts_pass_not_something_else(self):
        text = CMD.read_text(encoding="utf-8")
        assert "python -m scripts.run_alerts" in text


class TestTheRegisteredTaskIsUsable:
    def test_the_command_is_the_whole_path_not_a_truncated_prefix(
        self, registered_task_xml
    ):
        command = re.search(r"<Command>(.*?)</Command>", registered_task_xml, re.S)
        arguments = re.search(r"<Arguments>(.*?)</Arguments>", registered_task_xml, re.S)
        assert command, "no Command element - the task is not an Exec action"

        cmd = command.group(1).strip()
        arg = arguments.group(1).strip() if arguments else ""

        assert cmd.endswith("run_alerts.cmd"), (
            f"Command {cmd!r} looks truncated - schtasks split a spaced path "
            f"and the task will fail with file-not-found on every run"
        )
        assert arg == "", f"the path leaked into Arguments ({arg!r})"

    def test_the_command_exists_on_disk(self, registered_task_xml):
        cmd = re.search(r"<Command>(.*?)</Command>", registered_task_xml, re.S).group(1)
        assert Path(cmd.strip()).exists(), (
            f"the registered command {cmd!r} does not exist - every run will "
            f"fail with file-not-found"
        )

    def test_it_runs_every_hour(self, registered_task_xml):
        interval = re.search(r"<Interval>(.*?)</Interval>", registered_task_xml, re.S)
        assert interval, "no repetition interval - the task may run only once"
        assert interval.group(1).strip().upper() == "PT1H"

    def test_it_runs_as_the_logged_on_user_with_no_stored_password(
        self, registered_task_xml
    ):
        logon = re.search(r"<LogonType>(.*?)</LogonType>", registered_task_xml, re.S)
        assert logon, "no LogonType element"
        assert logon.group(1).strip() == "InteractiveToken", (
            "anything other than InteractiveToken means a Windows password is "
            "stored in the task"
        )

    def test_it_does_not_request_elevated_rights(self, registered_task_xml):
        level = re.search(r"<RunLevel>(.*?)</RunLevel>", registered_task_xml, re.S)
        assert level is None or level.group(1).strip() == "LeastPrivilege", (
            "the task requests elevated rights, which it has no reason to"
        )

    def test_it_catches_up_after_a_missed_run(self, registered_task_xml):
        node = re.search(r"<StartWhenAvailable>(.*?)</StartWhenAvailable>",
                         registered_task_xml, re.S)
        assert node and node.group(1).strip() == "true"

    def test_the_last_run_succeeded(self):
        """The check that catches a broken registration: not the exit code of
        `schtasks`, but the task's own last result."""
        out = _schtasks("/query", "/tn", TASK_NAME, "/fo", "LIST", "/v")
        if not out or "ERROR:" in out:
            pytest.skip(f"{TASK_NAME} is not registered on this machine")
        result = re.search(r"Last Result:\s*(\S+)", out)
        assert result, "could not read the task's last result"
        assert result.group(1) == "0", (
            f"the task's last run returned {result.group(1)} - it is failing "
            f"unattended; run it by hand to see the error"
        )
