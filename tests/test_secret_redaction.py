r"""A credential belongs in `.env`, never in `be.log`.

A4. Two ways the same secret escaped here:

  1. `requests` puts the URL it failed on into the exception it raises, query
     string included — and SerpApi authenticates by query string. So every
     `print(f"... {e}")` on a failure path wrote the live key to disk.
  2. The GitHub PAT was embedded in the `origin` remote URL.

The first is a regression test below: run a real `_get_json` failure with a
known key and assert the key is nowhere in stdout. The second is checked
against the repository itself — a token in a tracked file or in `origin`
fails the build, because the next commit would leak it again.

SerpApi documents 429 for BOTH "you are sending too fast" and "your account
has run out of searches", distinguishable only by the body. Reading that
body before `raise_for_status()` is what lets an exhausted account report
itself honestly instead of as a rate limit (C13).
"""

import re
import shutil
import subprocess

import pytest
import requests

import scrapers.serpapi_discovery as sd
from utils.redact import scrub

SECRET = "TESTKEYnotARealKey0123456789abcdef"

pytestmark = pytest.mark.usefixtures("_no_network")


@pytest.fixture()
def _no_network(monkeypatch):
    """Nothing here may reach serpapi.com — every test stubs its own
    response, and a missed stub fails loudly instead of spending a search."""
    def _blocked(*args, **kwargs):
        raise AssertionError("network call attempted — this file runs offline")

    monkeypatch.setattr(sd.requests, "get", _blocked)


def _budget(limit=10):
    return sd._Budget(limit)


# ---------------------------------------------------------------------------
# 1. Redaction is airtight
# ---------------------------------------------------------------------------

class TestScrubNeverLetsACredentialThrough:
    @pytest.mark.parametrize(
        "text",
        [
            f"https://serpapi.com/search.json?engine=google_shopping&api_key={SECRET}",
            f"https://serpapi.com/search.json?apikey={SECRET}&q=drill",
            f"https://example.com/?key={SECRET}",
            f"https://example.com/?token={SECRET}&x=1",
            f"https://example.com/?access_token={SECRET}",
            f"https://example.com/?secret={SECRET}",
        ],
    )
    def test_it_redacts_every_credential_shaped_query_parameter(self, text):
        assert SECRET not in scrub(text)
        assert "[REDACTED]" in scrub(text)

    def test_it_redacts_an_authorization_header(self):
        out = scrub(f"401 Client Error for url: https://x/y  Authorization: Bearer {SECRET}")

        assert SECRET not in out
        assert "Bearer [REDACTED]" in out

    def test_it_leaves_ordinary_text_alone(self):
        url = "https://www.ebay.co.uk/itm/12345?var=5678&cb=9"

        assert scrub(url) == url

    @pytest.mark.parametrize("value", [None, 42, b"api_key=abc", object()])
    def test_it_never_raises(self, value):
        """It runs INSIDE an error handler — a crash here would hide the
        original failure and lose the redaction with it."""
        out = scrub(value)
        assert isinstance(out, str)

    def test_it_still_reports_that_a_key_was_present(self):
        """Redaction must not erase the evidence that a credential was
        involved — the operator needs to know to rotate, not to wonder."""
        out = scrub(f"request failed: api_key={SECRET}")

        assert "api_key=[REDACTED]" in out


# ---------------------------------------------------------------------------
# 2. Exhaustion is distinguished from a rate limit
# ---------------------------------------------------------------------------

class _Response:
    def __init__(self, status, body=None, error=None):
        self.status_code = status
        self._body = body or {}
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error
        return None

    def json(self):
        return self._body


def _get(monkeypatch, response):
    """Stub `requests.get` and return the list of URLs it was called with."""
    seen: list[str] = []

    def fake(url, params=None, timeout=None, **kw):
        seen.append(url)
        return response

    monkeypatch.setattr(sd.requests, "get", fake)
    return seen


class TestAnExhaustedAccountIsNotARateLimit:
    def test_the_exhausted_body_stops_the_budget(self, monkeypatch):
        budget = _budget()
        _get(monkeypatch, _Response(429, {"error": "Your account has run out of searches."}))

        assert sd._get_json({"engine": "google_shopping"}, SECRET, budget) is None
        assert budget.exhausted is True

    def test_a_throughput_429_does_not_mark_the_account_exhausted(
        self, monkeypatch
    ):
        budget = _budget()
        _get(monkeypatch, _Response(429, {"error": "Too many requests."}))

        assert sd._get_json({"engine": "google_shopping"}, SECRET, budget) is None
        # A rate limit is temporary; treating it as an empty account would
        # shut discovery down for the rest of the month.
        assert budget.exhausted is False

    def test_once_exhausted_no_further_request_is_attempted(
        self, monkeypatch, capsys
    ):
        budget = _budget()
        seen = _get(
            monkeypatch,
            _Response(429, {"error": "Your account has run out of searches."}),
        )

        assert sd._search_shopping("drill", SECRET, budget) is None
        first_calls = len(seen)
        assert first_calls == 1

        # The remaining offers for every supplier would each retry into the
        # same wall. The budget is what stops them.
        budget.left = 99
        assert sd._search_shopping("drill", SECRET, budget) is None
        assert len(seen) == first_calls, "an exhausted account must not be re-asked"
        assert budget.left == 99

    def test_the_exhaustion_is_reported_as_exhaustion(
        self, monkeypatch, capsys
    ):
        budget = _budget()
        _get(monkeypatch, _Response(429, {"error": "Your account has run out of searches."}))

        sd._get_json({"engine": "google_shopping"}, SECRET, budget)

        out = capsys.readouterr().out
        assert "run out of searches" in out
        assert "unavailable" in out
        assert "rate limited" not in out

    def test_a_rate_limit_is_reported_as_rate_limiting(
        self, monkeypatch, capsys
    ):
        budget = _budget()
        _get(monkeypatch, _Response(429, {"error": "Too many requests."}))

        sd._get_json({"engine": "google_shopping"}, SECRET, budget)

        out = capsys.readouterr().out
        assert "rate limited" in out
        assert "run out of searches" not in out


# ---------------------------------------------------------------------------
# 3. The key never reaches stdout — the actual leak regression
# ---------------------------------------------------------------------------

class TestTheKeyNeverReachesTheLog:
    def test_a_failed_request_logs_no_credential(self, monkeypatch, capsys):
        """THE regression. `requests` builds its HTTPError from the URL, key
        included; without scrub() this single line put the working credential
        into be.log in clear text."""
        error = requests.HTTPError(
            f"500 Server Error for url: {sd.SERPAPI_BASE}"
            f"?engine=google_shopping&q=drill&api_key={SECRET}"
        )
        _get(monkeypatch, _Response(500, error=error))

        sd._get_json({"engine": "google_shopping"}, SECRET, _budget())

        out = capsys.readouterr().out
        assert SECRET not in out
        assert "api_key=[REDACTED]" in out

    def test_a_transport_failure_logs_no_credential(self, monkeypatch, capsys):
        def explode(url, params=None, timeout=None, **kw):
            raise requests.ConnectionError(
                f"connection reset for {sd.SERPAPI_BASE}?api_key={SECRET}"
            )

        monkeypatch.setattr(sd.requests, "get", explode)

        sd._get_json({"engine": "google_shopping"}, SECRET, _budget())

        assert SECRET not in capsys.readouterr().out

    def test_a_missing_key_warning_does_not_print_the_key(self, monkeypatch, capsys):
        """The 'not set' branch prints nothing secret, but it is the same
        line style — keep it honest."""
        monkeypatch.setenv("SERPAPI_KEY", "")
        sd.discover("drill")

        assert SECRET not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 4. Repository hygiene: no PAT in tracked files or in `origin`
# ---------------------------------------------------------------------------

PAT = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")

pytestmark_repo = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not on PATH"
)


@pytestmark_repo
class TestNoTokenIsCommitted:
    def _git(self, *args, cwd=None):
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, cwd=cwd, timeout=60
        )

    def test_no_tracked_file_contains_a_github_token(self):
        root = self._git("rev-parse", "--show-toplevel").stdout.strip()
        assert root, "could not locate the repository root"

        found = self._git(
            "grep", "-I", "-n", "-E", r"gh[pousr]_[A-Za-z0-9]{20,}", "--", ".", cwd=root
        )

        # git grep exits 1 with no output when nothing matches.
        assert found.returncode != 0 or not found.stdout.strip(), (
            "a GitHub token is tracked in the repository:\n" + found.stdout
        )

    def test_the_remote_url_carries_no_token(self):
        remotes = self._git("remote", "-v").stdout

        assert not PAT.search(remotes), (
            "the remote URL still embeds a token — push would keep it alive:\n"
            + remotes
        )
