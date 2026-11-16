import { describe, expect, it } from "vitest";

import { STORED_SCORE_TITLE, storedMatchScoreLabel } from "./matchScore";

/**
 * The History replay holds a stored C14 score but not the tier it was filed
 * under. These cases pin the boundary: a score is shown as a score, and
 * nothing here can label a row verified or unconfirmed.
 */

describe("storedMatchScoreLabel", () => {
  it("prints a real score at two decimals", () => {
    expect(storedMatchScoreLabel(0.5885)).toBe("Match score 0.59");
    expect(storedMatchScoreLabel(1)).toBe("Match score 1.00");
    expect(storedMatchScoreLabel(0)).toBe("Match score 0.00");
  });

  it("never claims a tier", () => {
    const label = storedMatchScoreLabel(0.9) ?? "";
    expect(label.toLowerCase()).not.toContain("verified");
    expect(label.toLowerCase()).not.toContain("confirmed");
    expect(STORED_SCORE_TITLE.toLowerCase()).toContain("no tier is claimed");
  });

  it("draws nothing for an absent or impossible score", () => {
    expect(storedMatchScoreLabel(null)).toBeNull();
    expect(storedMatchScoreLabel(undefined)).toBeNull();
    expect(storedMatchScoreLabel(Number.NaN)).toBeNull();
    expect(storedMatchScoreLabel(1.4)).toBeNull();
    expect(storedMatchScoreLabel(-0.1)).toBeNull();
  });
});
