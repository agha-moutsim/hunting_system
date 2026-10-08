r"""B1. The route cannot own the run's clock.

Measured on this box (2026-10-08): a full Deep Search costs 282.4s
(130.6s prompt evaluation of 1611 tokens + 149.7s generating 411), while
the route that carried it was allowed 120s. It therefore timed out on
every single call, and `_partial_or_timeout` did its best to hand back
whatever the sink had caught by then - damage limitation, not a solution:
the LLM verdict never arrived, and the user waited two minutes to be told
the run had been cut short.

The fix stops putting the run inside the request:

  * POST creates a job and returns its id in milliseconds, so nothing
    races a route timeout,
  * the run executes in the background with a budget sized for the
    measured cost rather than for an HTTP connection,
  * GET reports what the sink has published so far, with job_status on
    every poll so the UI can say "still running" or "failed" instead of
    rendering an empty verdict (the C13 rule, applied to a job).

The registry is deliberately in-memory with a TTL. A restart losing an
in-flight job is honest: the poll then 404s and the UI stops. A database
table would promise persistence that would then have to be honoured.

SEAM: everything below drives the real worker. The single stub is
``deep_search.deep_search_product`` - exactly what the worker calls. No
route helper is monkeypatched, so if the threading, the status bookkeeping
or the pruning breaks, these tests break with it.
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient

import api.deep_search as ads
from deep_search import DeepSearchResult


@pytest.fixture()
def client():
    from main import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_registry():
    """Jobs are module state; without this one test's jobs leak into the
    next and a TTL set by one test expires another's job."""
    with ads._LOCK:
        ads._JOBS.clear()
    yield
    with ads._LOCK:
        ads._JOBS.clear()


def _stub(monkeypatch, fn):
    """Point the worker's one dependency at ``fn``."""
    monkeypatch.setattr("deep_search.deep_search_product", fn)
    return fn


def _record(monkeypatch, *, delay=0.0, fail=False, block=None):
    """A run that returns immediately, sleeps, or raises."""
    calls = {}

    def _run(query, budget_s=None, sink=None):
        calls["query"] = query
        calls["budget"] = budget_s
        calls["sink"] = sink
        if block is not None:
            block[0].set()
            block[1].wait(5)
        if delay:
            time.sleep(delay)
        if fail:
            raise RuntimeError("Ollama is not running")
        return DeepSearchResult(product_name=query, verdict="PASS")

    _stub(monkeypatch, _run)
    return calls


def _start(client, query="drill") -> str:
    res = client.post("/api/deep-search", json={"query": query})
    assert res.status_code == 200
    return res.json()["job_id"]


def _poll(client, job_id):
    return client.get(f"/api/deep-search/jobs/{job_id}")


def _await_terminal(client, job_id, timeout=5.0) -> dict:
    """Poll until the worker is done - so no test leaves a live thread."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = _poll(client, job_id).json()
        if body.get("job_status") != "running":
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never left 'running'")


class TestPostHandsBackAJobInsteadOfARun:
    def test_it_returns_a_job_id(self, client, monkeypatch):
        _record(monkeypatch)
        body = client.post("/api/deep-search", json={"query": "drill"}).json()

        assert isinstance(body["job_id"], str) and body["job_id"]
        assert body["status"] == "running"
        assert body["query"] == "drill"

    def test_it_does_not_wait_for_the_run(self, client, monkeypatch):
        """The whole point of B1. A run that takes half a second must not
        be visible in the response time of the request that spawned it."""
        _record(monkeypatch, delay=0.5)
        job_id = _start(client)  # timing the POST itself

        start = time.monotonic()
        second = client.post("/api/deep-search", json={"query": "again"})
        elapsed = time.monotonic() - start

        assert second.status_code == 200
        assert elapsed < 0.4, f"POST blocked for {elapsed:.2f}s"
        _await_terminal(client, job_id)

    def test_a_running_job_is_reported_as_running(self, client, monkeypatch):
        """Deterministic: the stub signals it has started and then waits,
        so the poll is taken while the worker is genuinely mid-flight."""
        started, release = threading.Event(), threading.Event()
        _record(monkeypatch, block=(started, release))

        job_id = _start(client)
        assert started.wait(2), "worker never started"

        try:
            body = _poll(client, job_id).json()
            assert body["job_status"] == "running"
            # a job that has produced nothing still answers in the shape
            # the UI renders, rather than 204/empty
            assert body["product_name"] == "drill"
            assert "provenance" in body
        finally:
            release.set()
        _await_terminal(client, job_id)

    def test_each_query_gets_its_own_job(self, client, monkeypatch):
        _record(monkeypatch, delay=0.3)
        first = _start(client, "a")
        second = _start(client, "b")

        assert first != second
        _await_terminal(client, first)
        _await_terminal(client, second)
        assert _poll(client, first).json()["product_name"] == "a"
        assert _poll(client, second).json()["product_name"] == "b"


class TestPollingHandsWithBackTheRealResult:
    def test_a_finished_job_carries_the_provenance_block(self, client, monkeypatch):
        _record(monkeypatch)
        job_id = _start(client)

        body = _await_terminal(client, job_id)

        assert body["job_status"] == "complete"
        assert body["product_name"] == "drill"
        # C13 - a poll answers with the same pinned block a direct call did.
        assert isinstance(body["provenance"], dict)
        assert "fields" in body["provenance"]

    def test_a_worker_failure_is_reported_not_raised(self, client, monkeypatch):
        """The thread dies; the poll must still answer, and must say the
        job failed rather than showing an empty payload as if it ran."""
        _record(monkeypatch, fail=True)
        job_id = _start(client)

        res = _poll(client, job_id)
        assert res.status_code == 200
        body = _await_terminal(client, job_id)

        assert body["job_status"] == "failed"
        assert "Ollama is not running" in (body.get("job_error") or "")
        assert "failed" in (body.get("notes") or "").lower()
        # and the failure is what makes the data unverified - not a blank
        # object wearing an earned stamp (C13)
        assert body["provenance"]["demand"]["provenance"] == "unverified"

    def test_an_unknown_job_is_404(self, client):
        assert client.get("/api/deep-search/jobs/nope").status_code == 404


class TestTheRegistryForgets:
    def test_an_expired_job_404s_rather_than_serving_stale_data(
        self, client, monkeypatch
    ):
        _record(monkeypatch, delay=0.3)
        job_id = _start(client)
        _await_terminal(client, job_id)

        monkeypatch.setattr(ads, "JOB_TTL_S", 0.0)
        time.sleep(0.01)
        res = _poll(client, job_id)

        assert res.status_code == 404
        assert job_id not in ads._JOBS

    def test_pruning_leaves_a_live_job_alone(self, client, monkeypatch):
        _record(monkeypatch, delay=0.3)
        job_id = _start(client)
        _await_terminal(client, job_id)

        monkeypatch.setattr(ads, "JOB_TTL_S", 3600.0)
        ads._prune_jobs()

        assert job_id in ads._JOBS
        assert _poll(client, job_id).status_code == 200

    def test_a_finished_job_is_swept_eventually(self, client, monkeypatch):
        _record(monkeypatch)
        job_id = _start(client)
        _await_terminal(client, job_id)
        assert _poll(client, job_id).status_code == 200

        monkeypatch.setattr(ads, "JOB_TTL_S", 0.0)
        time.sleep(0.01)
        ads._prune_jobs()

        assert job_id not in ads._JOBS

    def test_the_ttl_stays_above_the_budget(self):
        """Swap the two and an overrunning job would be swept before its
        own timeout could ever be reported to the caller."""
        assert ads.JOB_TTL_S > ads.JOB_BUDGET_S


class TestTheBackgroundBudgetFitsTheMeasuredCost:
    def test_the_budget_is_sized_for_the_run_not_for_an_http_call(self):
        """A full run measured 282.4s and the old route budget was 120s,
        which is why every call ended in a timeout. A background job has
        no connection to protect, so its budget is the run's own cost."""
        assert ads.JOB_BUDGET_S >= 300
        assert ads.JOB_BUDGET_S > ads.FULL_TIMEOUT_S

    def test_the_worker_passes_that_budget_to_the_run(self, monkeypatch):
        seen: dict = {}

        def _run(query, budget_s=None, sink=None):
            seen["budget"] = budget_s
            seen["sink"] = sink
            return DeepSearchResult(product_name=query)

        _stub(monkeypatch, _run)
        from api.schemas import DeepSearchRequest

        job = ads.deep_search(DeepSearchRequest(query="drill"))
        ads._execute_job(ads._JOBS[job["job_id"]])

        assert seen["budget"] == ads.JOB_BUDGET_S
        assert isinstance(seen["sink"], dict)
        assert ads._JOBS[job["job_id"]]["status"] == "complete"
