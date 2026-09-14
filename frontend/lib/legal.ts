/**
 * Who operates this site.
 *
 * German law (§ 5 DDG, formerly § 5 TMG) requires a business website to name
 * its operator with a postal address and a way to reach them. Those details
 * belong to a person, not to a repository, so they are read from the
 * environment and nothing here invents them.
 *
 * When they are absent the Impressum says so plainly. That is not a nice
 * touch: an Impressum with a placeholder name in it is worse than a page
 * admitting the site is not ready to be published, because the first one looks
 * finished and is false.
 */

export interface Operator {
  name: string;
  address: string[];
  email: string;
  /** Optional: only some operators have these, and an empty one is not a gap. */
  phone?: string;
  register?: string;
  vatId?: string;
}

function lines(value: string | undefined): string[] {
  return (value ?? "")
    .split(/[\n;|]/)
    .map((line) => line.trim())
    .filter(Boolean);
}

/**
 * The operator, or null when this deployment has not been told who it is.
 *
 * Requires a name, a postal address and an email together: two out of three is
 * not a lawful Impressum, and publishing a partial one would be claiming
 * compliance that does not exist.
 */
export function operator(): Operator | null {
  const name = process.env.LEGAL_OPERATOR_NAME?.trim();
  const address = lines(process.env.LEGAL_OPERATOR_ADDRESS);
  const email = process.env.LEGAL_OPERATOR_EMAIL?.trim();

  if (!name || address.length === 0 || !email) return null;

  return {
    name,
    address,
    email,
    phone: process.env.LEGAL_OPERATOR_PHONE?.trim() || undefined,
    register: process.env.LEGAL_OPERATOR_REGISTER?.trim() || undefined,
    vatId: process.env.LEGAL_OPERATOR_VAT_ID?.trim() || undefined,
  };
}

/** The date the privacy notice below was last changed, by hand, on purpose. */
export const PRIVACY_LAST_UPDATED = "14 September 2026";
