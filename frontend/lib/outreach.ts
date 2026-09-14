/**
 * Building the "open this in my mail client" links.
 *
 * The backend builds these too, for callers that already know the address.
 * Here they are rebuilt as somebody types one, because re-asking the server on
 * every keystroke to change a single query parameter would be a round trip for
 * nothing. Two implementations of one format is a real cost, so both are
 * tested and neither is allowed to be the clever one.
 *
 * Neither of these sends anything. They open a compose window with the message
 * already in it, and a person presses send - which is what keeps the buyer the
 * sender, and this product out of the business of contacting companies.
 */

/** Gmail stops honouring very long URLs, and truncates rather than complains. */
export const MAX_URL_LENGTH = 7000;

export interface Draft {
  to: string;
  subject: string;
  body: string;
}

/** A Gmail compose window, pre-filled. `view=cm` is compose; there is no
 *  parameter that sends, and none is wanted. */
export function gmailUrl({ to, subject, body }: Draft): string {
  const query = new URLSearchParams({ view: "cm", fs: "1", to, su: subject, body });
  return `https://mail.google.com/mail/?${query.toString()}`;
}

/** The same message, for whatever mail client this machine prefers. */
export function mailtoUrl({ to, subject, body }: Draft): string {
  const query = new URLSearchParams({ subject, body });
  return `mailto:${encodeURIComponent(to)}?${query.toString()}`;
}

/**
 * Whether the links can carry this message intact.
 *
 * Reported rather than worked around: a link that quietly drops the last
 * paragraph puts half an enquiry in front of a supplier, and the sender would
 * have no way of knowing.
 */
export function fitsInAUrl(draft: Draft): boolean {
  return Math.max(gmailUrl(draft).length, mailtoUrl(draft).length) <= MAX_URL_LENGTH;
}

/**
 * Whether an address is worth putting in a link at all.
 *
 * Deliberately permissive - one @ with something either side. Anything
 * stricter rejects addresses that work, and the real check is the mail client
 * refusing to send, which happens a moment later and knows more than we do.
 */
export function looksLikeAnAddress(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed || /\s/.test(trimmed)) return false;
  const [local, domain, ...rest] = trimmed.split("@");
  if (rest.length > 0 || !local || !domain) return false;
  return domain.includes(".");
}
