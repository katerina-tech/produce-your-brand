/**
 * Joining dictated speech onto text somebody may already have typed.
 *
 * Pulled out of the component because it is the only part with decisions in
 * it, and decisions deserve tests. Everything else in dictation is browser
 * API plumbing that a test could only restate.
 *
 * Speech recognition hands back fragments with no leading space and no
 * awareness of what came before, so joining is ours to get right: a fragment
 * appended blindly produces "100 tote bagsdelivered to Potsdam", and a
 * fragment always preceded by a space produces " Hello" in an empty box and
 * "end of sentence ." after punctuation.
 */

/** Characters after which a space would be wrong. */
const NO_SPACE_BEFORE = new Set([",", ".", ";", ":", "!", "?", ")", "]", "}", "…"]);

/**
 * Append a dictated fragment to existing text, spacing it the way a person
 * would. Returns the whole new value, so a caller can assign it directly.
 */
export function appendDictation(existing: string, fragment: string): string {
  const chunk = fragment.trim();
  if (!chunk) return existing;

  // An empty box starts at the beginning, not at a space.
  if (!existing) return chunk;

  const endsWithSpace = /\s$/.test(existing);
  // charAt, not [0]: the trimmed chunk is non-empty here, but charAt says so
  // to the type checker instead of asking it to take our word for it.
  const startsWithPunctuation = NO_SPACE_BEFORE.has(chunk.charAt(0));

  if (endsWithSpace || startsWithPunctuation) {
    // Recogniser fragments sometimes arrive as bare punctuation; gluing it to
    // the previous word is right, and so is not doubling an existing space.
    return startsWithPunctuation ? existing.replace(/\s+$/, "") + chunk : existing + chunk;
  }

  return `${existing} ${chunk}`;
}

/**
 * The languages offered for dictation.
 *
 * Two, not twenty. This product is used in Berlin by people describing a
 * production job, and a list long enough to need scrolling would be a worse
 * answer than the two languages those conversations actually happen in.
 */
export const DICTATION_LANGUAGES = [
  { code: "en-US", label: "English" },
  { code: "de-DE", label: "Deutsch" },
] as const;

export type DictationLanguage = (typeof DICTATION_LANGUAGES)[number]["code"];

/** Which language to start in, given the browser's own preference. */
export function preferredLanguage(browserLanguage: string | undefined): DictationLanguage {
  return browserLanguage?.toLowerCase().startsWith("de") ? "de-DE" : "en-US";
}
