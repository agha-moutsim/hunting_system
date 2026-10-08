/**
 * B1 — the full Deep Search route no longer returns a result.
 *
 * It returns a job id, and this page polls for the verdict. That split
 * exists because a full run costs 282.4 seconds on this machine while the
 * HTTP call that used to carry it was allowed 240: it timed out on every
 * attempt, so the LLM verdict never arrived.
 *
 * The polling loop has two failure modes worth a named function each:
 *   - never stopping, which hangs the page on a spinner forever,
 *   - stopping while the job is still alive, which silently discards a
 *     run that was going to answer.
 * Both are decided here so they can be tested without a network.
 */

import { DeepSearchResult } from "./types";

/** What the poll endpoint adds to an ordinary DeepSearchResult. */
export interface DeepSearchJobResult extends DeepSearchResult {
  job_id?: string;
  job_status?: string;
  job_error?: string;
}

/** What POST /api/deep-search answers with. */
export interface JobStarted {
  job_id: string;
  status: string;
  query: string;
}

export const JOB_POLL_INTERVAL_MS = 1_000;

/**
 * How long the client keeps asking before it gives up.
 *
 * The server's own JOB_BUDGET_S is 300s. Past that plus margin, a job that
 * has not reported is either wedged or was lost to a backend restart — and
 * an eternal poll is worse than an honest stop, because the page would sit
 * on a spinner the user cannot argue with.
 */
export const JOB_MAX_WAIT_MS = 420_000;

/** Statuses after which the server will never change its answer. */
export function isTerminalJobStatus(
  status: string | null | undefined
): boolean {
  return status === "complete" || status === "failed" || status === "timed_out";
}

/**
 * Milliseconds to wait before the next poll, or null to stop polling.
 *
 * `attempts` counts polls already made, so 0 asks for the first delay.
 */
export function nextPollDelay(attempts: number): number | null {
  if (attempts * JOB_POLL_INTERVAL_MS >= JOB_MAX_WAIT_MS) return null;
  return JOB_POLL_INTERVAL_MS;
}

/** The job has failed or overrun — say why, but keep any partial data. */
export function jobFailureMessage(body: DeepSearchJobResult): string | null {
  if (!isTerminalJobStatus(body.job_status)) return null;
  if (body.job_status === "complete") return null;
  if (body.job_error) return body.job_error;
  if (body.job_status === "timed_out") {
    return "The background run did not finish in time. Showing the work it had done.";
  }
  return "The background job failed before it could produce a verdict.";
}
