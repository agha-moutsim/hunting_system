import { describe, it, expect } from "vitest";
import {
  isTerminalJobStatus,
  nextPollDelay,
  jobFailureMessage,
  JOB_POLL_INTERVAL_MS,
  JOB_MAX_WAIT_MS,
  DeepSearchJobResult,
} from "./deepSearchJob";

/** The polling contract only ever looks at the job fields, so a partial
 * object is enough — every test here is about the decision, not the data. */
const job = (o: Partial<DeepSearchJobResult>) => o as DeepSearchJobResult;

describe("isTerminalJobStatus", () => {
  it("stops on every status the server will not change again", () => {
    for (const s of ["complete", "failed", "timed_out"]) {
      expect(isTerminalJobStatus(s)).toBe(true);
    }
  });

  it("keeps polling while the job is alive or unknown", () => {
    for (const s of ["running", undefined, null, "", "RUNNING", "bogus"]) {
      expect(isTerminalJobStatus(s)).toBe(false);
    }
  });

  it("does not treat the POST hand-off as terminal", () => {
    // POST answers {status: "running"} — polling on that must not stop.
    expect(isTerminalJobStatus("running")).toBe(false);
  });
});

describe("nextPollDelay", () => {
  it("waits the interval before the first poll", () => {
    expect(nextPollDelay(0)).toBe(JOB_POLL_INTERVAL_MS);
  });

  it("keeps polling right up to the cap", () => {
    const last = JOB_MAX_WAIT_MS / JOB_POLL_INTERVAL_MS - 1;
    expect(nextPollDelay(last)).toBe(JOB_POLL_INTERVAL_MS);
  });

  it("stops at the cap instead of polling forever", () => {
    const first = JOB_MAX_WAIT_MS / JOB_POLL_INTERVAL_MS;
    expect(nextPollDelay(first)).toBeNull();
    expect(nextPollDelay(first + 1_000)).toBeNull();
  });

  it("waits longer than the server's own run budget", () => {
    // Give up too early and a run that was still working is abandoned.
    expect(JOB_MAX_WAIT_MS).toBeGreaterThan(300_000);
  });
});

describe("jobFailureMessage", () => {
  it("stays silent while the job is still running", () => {
    expect(jobFailureMessage(job({ job_status: "running" }))).toBeNull();
  });

  it("stays silent on success", () => {
    expect(jobFailureMessage(job({ job_status: "complete" }))).toBeNull();
  });

  it("reports the server's own reason when it sent one", () => {
    const msg = jobFailureMessage(
      job({ job_status: "failed", job_error: "Ollama is not running" })
    );
    expect(msg).toBe("Ollama is not running");
  });

  it("explains a timeout even when the server sent no reason", () => {
    const msg = jobFailureMessage(job({ job_status: "timed_out" }));
    expect(msg).toMatch(/did not finish/i);
    // partial data is still shown, so the message must not read as a loss
    expect(msg).toMatch(/showing the work/i);
  });

  it("never leaves a failure with nothing to say", () => {
    expect(jobFailureMessage(job({ job_status: "failed" }))).toBeTruthy();
  });
});
