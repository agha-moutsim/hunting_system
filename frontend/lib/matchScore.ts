/**
 * A stored C14 matcher score, labelled as a score and never as a tier.
 *
 * History replays supplier rows that were stored with their score but not the
 * tier they were filed under. Printing "Match verified" beside that number
 * would claim a classification the database cannot prove, so the replay says
 * only what it holds. An absent or out-of-range score gets no label at all.
 */

export const STORED_SCORE_TITLE =
  "The C14 matcher scored this pair when the analysis ran. The tier it was " +
  "filed under was not stored, so no tier is claimed here.";

export function storedMatchScoreLabel(
  score?: number | null
): string | null {
  if (typeof score !== "number" || !Number.isFinite(score)) return null;
  // `match_score` is a 0..1 column. A number outside that range is not a
  // score, so it is not shown as one.
  if (score < 0 || score > 1) return null;
  return `Match score ${score.toFixed(2)}`;
}
