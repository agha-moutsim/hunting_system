r"""The scheduled task must actually run the monitor.

A scheduled task that fails to register, or that points at a path which does not
exist, produces no error anywhere the user is looking. It simply never samples,
and every 7-day trend stays `unverified` forever with no visible cause. That
silence is the entire risk, so the registration is verified against the OS
rather than assumed from the command's exit code.

What this file found on a real machine, which is why the assertions are
pointed:

  * `Import-ScheduledTask` is unavailable - this machine has the
    ScheduledTasks module's manifest but not its native DLL, so every cmdlet
    in that module is missing. `/xml` registration therefore fails with
    "unable to switch the encoding", because Task Scheduler's XML reader
    requires real UTF-16.
  * `schtasks.exe /create /tr "<path with spaces>"` SILENTLY splits the path at
    the first space when the quoting does not survive the shell. The task
    registered happily with `C:\Users\Agha` as the executable and the rest as
    arguments, then failed every run with 0x80070002 (file not found) - with
    no log and nothing in the UI.

So the task is registered with the 8.3 short path, which contains no spaces,
and the tests below check the registered Command both for being un-split and
for existing on disk.

The OS-facing tests skip when the task is not registered, so the suite still
runs on another machine or in CI.
"""

import re
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
SCRIPTS = BACKEND / "scripts"
CMD = SCRIPTS / "run_demand_monitor.cmd"
TASK_NAME = "eBayHunter Demand Monitor"


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
        moves, and the task would keep failing every 6h with no log."""
        text = CMD.read_text(encoding="utf-8")
        assert "%~dp0" in text
        # no drive-letter absolute path baked into the script
        assert not re.search(r"[A-Za-z]:\\\\?Users", text, re.I)

    def test_the_log_path_is_absolute_not_relative(self):
        """The bug this whole file is about: Task Scheduler starts the process
        in its own working directory, so a relative `data\\...` would land
        somewhere unwritable and produce no log at all."""
        text = CMD.read_text(encoding="utf-8")
        assert re.search(r'>>\s*"%~dp0', text), (
            "the log redirect must be derived from %~dp0, not from the "
            "current directory"
        )

    def test_it_changes_directory_before_running(self):
        """`python -m scripts.run_demand_monitor` only resolves from backend/."""
        text = CMD.read_text(encoding="utf-8")
        assert 'pushd "%~dp0.."' in text

    def test_it_appends_rather_than_overwrites_the_log(self):
        """`>>` appends so each run's result is kept. The `2>&1` beside it also
        contains a bare `>`, so this checks the log redirect specifically rather
        than banning every `>` in the file."""
        text = CMD.read_text(encoding="utf-8")
        assert re.search(r'>>\s*"%~dp0\.\.[\\/]data[\\/]demand_monitor\.log"', text)
        assert not re.search(r"(?<![>0-9])>\s*\"%~dp0", text), (
            "the log is being overwritten rather than appended"
        )

    def test_it_propagates_the_exit_code(self):
        """Otherwise Task Scheduler always reports success and a failing
        monitor looks healthy forever."""
        text = CMD.read_text(encoding="utf-8").lower()
        assert "exit /b %rc%" in text

    def test_the_log_is_gitignored(self):
        gitignore = (BACKEND.parent / ".gitignore").read_text(encoding="utf-8")
        assert "*.log" in gitignore

    def test_the_python_module_it_calls_exists(self):
        assert (SCRIPTS / "run_demand_monitor.py").exists()


class TestTheRegisteredTaskIsUsable:
    def test_the_command_is_the_whole_path_not_a_truncated_prefix(
        self, registered_task_xml
    ):
        """The space-splitting failure, guarded properly.

        A space in the path is fine - the XML route carries it in one element.
        What is NOT fine is the path arriving truncated, which is what
        `schtasks /create /tr` did here: it registered a Command of
        `C:\\Users\\Agha` with the remainder in Arguments, and every run failed
        with 0x80070002 and no log.

        So the check is that the Command is the complete file: right name, and
        nothing leaked into Arguments.
        """
        command = re.search(r"<Command>(.*?)</Command>", registered_task_xml, re.S)
        arguments = re.search(r"<Arguments>(.*?)</Arguments>", registered_task_xml, re.S)
        assert command, "no Command element - the task is not an Exec action"

        cmd = command.group(1).strip()
        arg = arguments.group(1).strip() if arguments else ""

        assert cmd.endswith("run_demand_monitor.cmd"), (
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

    def test_it_runs_every_six_hours(self, registered_task_xml):
        interval = re.search(
            r"<Interval>(.*?)</Interval>", registered_task_xml, re.S
        ) or re.search(r"<Interval>(.*?)</Interval>", registered_task_xml)
        assert interval, "no repetition interval - the task may run only once"
        assert interval.group(1).strip().upper() == "PT6H"

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
        """Task Scheduler omits RunLevel from its query output when it is the
        default, and the default is LIMITED. So absent is fine; HIGHEST is not.
        """
        level = re.search(r"<RunLevel>(.*?)</RunLevel>", registered_task_xml, re.S)
        assert level is None or level.group(1).strip() == "LeastPrivilege", (
            "the task requests elevated rights, which it has no reason to"
        )

    def test_it_catches_up_after_a_missed_run(self, registered_task_xml):
        """A laptop that was asleep at the scheduled time must still sample -
        the gaps between samples are the measurement."""
        node = re.search(r"<StartWhenAvailable>(.*?)</StartWhenAvailable>",
                         registered_task_xml, re.S)
        assert node and node.group(1).strip() == "true"

    def test_the_last_run_succeeded(self):
        """The check that actually catches a broken registration: not the exit
        code of `schtasks`, but the task's own last result."""
        out = _schtasks("/query", "/tn", TASK_NAME, "/fo", "LIST", "/v")
        if not out or "ERROR:" in out:
            pytest.skip(f"{TASK_NAME} is not registered on this machine")
        result = re.search(r"Last Result:\s*(\S+)", out)
        assert result, "could not read the task's last result"
        assert result.group(1) == "0", (
            f"the task's last run returned {result.group(1)} - it is failing "
            f"unattended; run it by hand to see the error"
        )