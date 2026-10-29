"""Deep search endpoints — full (background job) and fast (no LLM).

B1 — the full route no longer owns the run.

Measured on this box: a full run costs 282.4s (130.6s of prompt evaluation
over 1611 tokens + 149.7s generating 411) while the route that carried it
was allowed 120s. It therefore timed out on EVERY call — the LLM verdict
never arrived, and the user waited two minutes to be told the run had been
cut short. `_partial_or_timeout` handed back whatever the sink had caught
by then, which is damage limitation, not a solution.

So the request and the run are now separate things:

  * POST creates a job and returns its id in milliseconds. Nothing can
    race a connection that has already been answered.
  * the run executes in the background with a budget sized for its own
    measured cost, not for an HTTP connection.
  * GET reports what the sink has published so far, carrying `job_status`
    on every poll so the UI can say "still running", "failed" or
    "timed out" instead of rendering an empty verdict (the C13 rule,
    applied to a job).

The registry is deliberately in-memory with a TTL: a restart losing an
in-flight job is honest — the poll then 404s and the UI stops. A database
table would promise persistence we would then have to honour.
"""

import asyncio
import logging
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException, Request

from api.market_context import marketplace_for_optional_request
from api.schemas import DeepSearchRequest
from api.provenance_block import build_provenance_block, unverified_stamp
from marketplaces import analyze_ready, fee_warning, get_marketplace

router = APIRouter()
logger = logging.getLogger(__name__)

# The synchronous route budgets. FAST still owns one — it has no LLM and
# finishes inside it. FULL is retained only as the floor the background
# budget must exceed: it is the budget the full path held before B1, which
# is precisely the budget that was too small.
FULL_TIMEOUT_S = 120.0
FAST_TIMEOUT_S = 75.0

# B1 — what a background run is allowed to take. The measured full run is
# 282.4s, so 300s gives it its real cost plus margin. A job has no
# connection to protect, so there is no reason to cut the model off mid
# verdict the way the route used to.
JOB_BUDGET_S = 300.0

# Jobs are remembered for this long after creation, then forgotten. Must
# stay above JOB_BUDGET_S or an overrun would be swept before its timeout
# could be reported.
JOB_TTL_S = 600.0

# id -> {"id", "query", "sink", "created", "status", "result"?, "job_error"?}
_JOBS: dict[str, dict] = {}
_LOCK = threading.RLock()


def _require_ready_market(request: Request | None, surface: str) -> dict:
    """The requested market, refused unless it can price a resale.

    `analyze_ready` is the right gate here, not UK-only: AU has a sourced
    card and an AUD supplier bench, so Deep Search can compare AUD with AUD.
    A market without a card or bench still cannot, and its refusal names the
    missing piece rather than pretending the feature is UK-only.
    """
    market = marketplace_for_optional_request(request)
    if analyze_ready(market):
        return market
    reason = fee_warning(market) or (
        "No supplier bench is registered for this marketplace."
    )
    raise HTTPException(
        status_code=422,
        detail=(
            f"{surface} is not enabled for {market['label']}. {reason}"
        ),
    )


@router.post("/deep-search")
def deep_search(req: DeepSearchRequest, request: Request = None) -> dict:
    """Start a full deep research job and hand back its id at once.

    Returns immediately with `job_id` + `status`. The run itself — eBay
    query, supplier scrapes, then the LLM verdict — happens on a worker
    thread. Poll GET /deep-search/jobs/{job_id} for progress.
    """
    market = _require_ready_market(request, "Deep Search")
    job = _create_job(req.query, market["id"])
    # Captured before the worker exists: read after _spawn_job this would
    # be a race, reporting whichever state the thread had reached by the
    # time the response was built. POST describes the creation, not the
    # outcome - the poll reports the outcome.
    status = job["status"]
    _spawn_job(job)
    logger.info(
        "Deep search job %s started for %r (%s)",
        job["id"], req.query, market["id"],
    )
    return {
        "job_id": job["id"],
        "status": status,
        "query": job["query"],
        "marketplace": market["id"],
        "currency": market["currency"],
        "currency_symbol": market["currency_symbol"],
    }


@router.get("/deep-search/jobs/{job_id}")
def deep_search_job(job_id: str) -> dict:
    """Report a job's current state — partial results included.

    The payload is always shaped like a DeepSearchResult, whether the run
    has finished or has barely begun, so the caller can render whatever it
    has without guarding every field.
    """
    _prune_jobs()
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(
                404,
                "Job not found — it either never existed or has expired.",
            )
        status = job["status"]
        query = job["query"]
        marketplace = job.get("marketplace", "EBAY_GB")
        job_error = job.get("job_error")
        sink_result = job["sink"].get("result")

        if status == "running" and time.monotonic() - job["created"] > JOB_BUDGET_S:
            # The thread cannot be cancelled, so this only decides what we
            # TELL the caller. It stays timed_out even if the worker limps
            # home afterwards: the answer it is waiting for has already
            # been declared late.
            status = "timed_out"
            job["status"] = "timed_out"
            job["job_error"] = (
                f"Background run did not finish within {int(JOB_BUDGET_S)}s"
            )
            job_error = job["job_error"]

        payload = _payload_for(
            status, query, sink_result, job_error, marketplace
        )
        payload["job_id"] = job_id
        payload["job_status"] = status
        if job_error:
            payload["job_error"] = job_error
        return payload


@router.post("/deep-search/fast")
def deep_search_fast(req: DeepSearchRequest, request: Request = None):
    """Fast deep research: eBay sold + key supplier scrapes, NO LLM (~15-45s).

    Still synchronous: with the model out of the picture it finishes inside
    FAST_TIMEOUT_S, so there is no job to poll for.
    """
    from deep_search import deep_search_fast as _fast

    market = _require_ready_market(request, "Deep Search")
    sink: dict = {}
    # UK keeps the historical three-argument call so existing test doubles
    # and the saved-search runner keep working; a non-UK run states its id.
    run_args = (
        (req.query, FAST_TIMEOUT_S, sink)
        if market["id"] == "EBAY_GB"
        else (req.query, FAST_TIMEOUT_S, sink, market["id"])
    )
    try:
        result = asyncio.run(
            asyncio.wait_for(
                _to_thread(_fast, *run_args),
                timeout=FAST_TIMEOUT_S,
            )
        )
    except (TimeoutError, asyncio.TimeoutError):
        return _partial_or_timeout(
            req.query, FAST_TIMEOUT_S, sink, full=False,
            marketplace=market["id"],
        )
    return _response(result)


def _create_job(query: str, marketplace: str = "EBAY_GB") -> dict:
    with _LOCK:
        _prune_jobs_locked()
        job = {
            "id": uuid.uuid4().hex,
            "query": query,
            "marketplace": marketplace,
            "sink": {},
            "created": time.monotonic(),
            "status": "running",
        }
        _JOBS[job["id"]] = job
        return job


def _spawn_job(job: dict) -> None:
    threading.Thread(
        target=_execute_job,
        args=(job,),
        name=f"deep-search-{job['id'][:8]}",
        daemon=True,
    ).start()


def _execute_job(job: dict) -> None:
    """Run the search for a job and record how it ended. Never raises.

    A thread has no caller to raise into — an unhandled exception here
    would print a traceback and leave the job "running" forever, so the
    failure has to be written into the job where the poll can read it.
    """
    from deep_search import deep_search_product

    marketplace = job.get("marketplace", "EBAY_GB")
    try:
        if marketplace == "EBAY_GB":
            result = deep_search_product(
                job["query"], JOB_BUDGET_S, job["sink"]
            )
        else:
            result = deep_search_product(
                job["query"], JOB_BUDGET_S, job["sink"], marketplace
            )
    except Exception as exc:  # noqa: BLE001 - the job record is the report
        logger.exception("Deep search job %s failed", job["id"])
        job["status"] = "failed"
        job["job_error"] = str(exc) or exc.__class__.__name__
        return

    job["result"] = result
    if job["status"] == "running":
        job["status"] = "complete"


def _prune_jobs() -> None:
    with _LOCK:
        _prune_jobs_locked()


def _prune_jobs_locked() -> None:
    cutoff = time.monotonic() - JOB_TTL_S
    for job_id in [k for k, v in _JOBS.items() if v["created"] < cutoff]:
        del _JOBS[job_id]


def _payload_for(status: str, query: str, sink_result, job_error: str | None,
                 marketplace: str = "EBAY_GB") -> dict:
    """Build the poll payload for one job status.

    An overrun answers with the run's own work via `_partial_or_timeout`,
    because the sink already holds everything the run finished fetching —
    throwing it away to say "timed out" is the exact failure B1 exists to
    stop.
    """
    if status == "timed_out":
        return _partial_or_timeout(
            query, JOB_BUDGET_S,
            {"result": sink_result} if sink_result else {},
            full=True, marketplace=marketplace,
        )

    from deep_search import DeepSearchResult
    market = get_marketplace(marketplace)

    if sink_result is None:
        blank = DeepSearchResult(
            product_name=query,
            marketplace=market["id"],
            currency=market["currency"],
            currency_symbol=market["currency_symbol"],
        )
        blank.verdict = "PENDING"
        if status == "failed":
            blank.notes = f"Background job failed: {job_error}"
        elif status == "running":
            blank.notes = "Background job still running — poll again shortly."
        else:
            blank.notes = "Background job finished without a result."
        payload = blank.to_dict()
        reason = f"background job {status}"
        if job_error:
            reason = f"{reason}: {job_error}"
        payload["provenance"] = build_provenance_block(payload, reason=reason)
        return payload

    payload = sink_result.to_dict()
    payload["provenance"] = build_provenance_block(payload)
    return payload


def _response(result) -> dict:
    """DeepSearchResult → payload carrying the pinned provenance block (C13).

    Both success paths hand the block through build_provenance_block so a
    run that fetched nothing can never wear the same stamp as one that did.
    """
    payload = result.to_dict()
    payload["provenance"] = build_provenance_block(payload)
    return payload


async def _to_thread(fn, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)


def _timeout_result(query: str, seconds: float, full: bool,
                    marketplace: str = "EBAY_GB") -> dict:
    from deep_search import DeepSearchResult

    market = get_marketplace(marketplace)
    r = DeepSearchResult(
        product_name=query,
        marketplace=market["id"],
        currency=market["currency"],
        currency_symbol=market["currency_symbol"],
    )
    r.verdict = "PENDING"
    r.notes = (
        f"Request timed out after {int(seconds)}s. "
        + ("Try Fast mode or retry." if full else "Supplier scrapers hung — retry.")
    )
    r.filters_passed.append({
        "name": "Data",
        "passed": False,
        "actual": f"Timed out after {int(seconds)}s",
        "expected": "Completed within budget",
        "verified": False,
    })
    # C11/C13 — a timeout discovered no stores: present-but-empty, stamped
    # unverified WITH a reason (exactly what /api/analyze's timeout does).
    reason = f"deep search timed out after {int(seconds)}s"
    r.ebay_stores_provenance = unverified_stamp(reason)
    logger.error("Deep search %s timed out after %.0fs (full=%s)", query, seconds, full)
    payload = r.to_dict()
    # C13 — nothing was fetched and nothing was computed, so every block
    # in the response reads unverified WITH why.
    payload["provenance"] = build_provenance_block(payload, reason=reason)
    return payload


def _partial_or_timeout(query: str, seconds: float, sink: dict | None,
                        *, full: bool,
                        marketplace: str = "EBAY_GB") -> dict:
    """Answer with whatever the run had already finished.

    A1.4 — and, after B1, what an overrunning background job answers with
    as well. `deep_search_product` publishes into ``sink`` between stages
    precisely so this branch has something to hand back: the run cannot be
    cancelled, so without the sink the fetch of a completed eBay query, its
    stores and every verified supplier would be discarded and the answer
    would be an all-zero object that looks like the product does not sell.

    The run's own stamps are kept rather than a blanket reason: what WAS
    fetched still reads verified (C13), and the overrun itself is reported
    where an overrun belongs — in ``filters_passed`` and ``notes``. Stamping
    fetched data "timed out" would trade one falsehood for another.
    """
    partial = (sink or {}).get("result")
    if partial is None:
        return _timeout_result(query, seconds, full, marketplace)

    if not partial.verdict:
        partial.verdict = "PENDING"
    late = (
        f"Timed out after {int(seconds)}s — returning the work already done; "
        "later stages did not run."
    )
    partial.notes = f"{partial.notes} {late}".strip()
    partial.filters_passed.append({
        "name": "Data",
        "passed": False,
        "actual": f"Timed out after {int(seconds)}s",
        "expected": "Completed within budget",
        "verified": False,
    })
    logger.warning("Deep search %s returned PARTIAL results after %.0fs (full=%s)",
                   query, seconds, full)
    payload = partial.to_dict()
    payload["provenance"] = build_provenance_block(payload)
    return payload
