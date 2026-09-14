"use client";

import { useState } from "react";

import { Card, CardHeader } from "@/components/ui";
import { fitsInAUrl, gmailUrl, looksLikeAnAddress, mailtoUrl } from "@/lib/outreach";
import type { Outreach } from "@/lib/types";

/**
 * The last step: contacting the partner.
 *
 * This opens a message; it never sends one. The distinction is the product's
 * legal position rather than a preference - a platform that contacts companies
 * itself becomes the sender under UWG §7 and has to hold their addresses,
 * which brings GDPR Art. 14 with it. A buyer writing to a supplier they chose
 * has neither problem. So the work of composing is done for them, and the one
 * irreversible act stays theirs.
 *
 * The text is shown but not editable here. It is the quotation request the
 * user approved a step ago, and an edit box would let it drift from what was
 * approved without anybody deciding to. Gmail is the right place to change a
 * word, and it is one click away.
 */
export function ContactPartner({ outreach }: { outreach: Outreach }) {
  const [to, setTo] = useState("");
  const [copied, setCopied] = useState(false);

  const draft = { to: to.trim(), subject: outreach.subject, body: outreach.body };
  const addressLooksWrong = to.trim().length > 0 && !looksLikeAnAddress(to);
  const tooLongForALink = !fitsInAUrl(draft);

  async function copy() {
    try {
      await navigator.clipboard.writeText(`${outreach.subject}\n\n${outreach.body}`);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2500);
    } catch {
      // A blocked clipboard is not worth an error panel: the text is on screen
      // and can be selected by hand.
      setCopied(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title={`Write to ${outreach.supplier_name}?`}
        hint="Your request is ready. Opening it fills in your email — you press send."
      />

      <div className="space-y-5 px-5 py-5 sm:px-6">
        <div>
          <label htmlFor="partner-email" className="mb-1.5 block text-sm font-medium">
            Their email address
          </label>
          <input
            id="partner-email"
            type="email"
            value={to}
            onChange={(event) => setTo(event.target.value)}
            placeholder="info@example.de"
            className="w-full rounded-lg border border-line bg-surface px-3.5 py-2.5 text-[15px] outline-none transition-colors focus:border-accent sm:max-w-md"
          />
          <p className="mt-1.5 text-xs text-ink-muted">
            This system stores no supplier addresses, so this one is yours to
            supply. You can also leave it blank and fill it in once the message
            opens.
          </p>
          {addressLooksWrong ? (
            <p className="mt-1.5 text-xs text-blocked">
              That does not look like an email address yet.
            </p>
          ) : null}
        </div>

        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">Subject</p>
          <p className="mt-1 text-sm font-medium">{outreach.subject}</p>

          <p className="mt-4 text-xs font-medium uppercase tracking-wide text-ink-muted">
            Message
          </p>
          <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-canvas px-3.5 py-3 font-sans text-sm leading-relaxed text-ink-soft">
            {outreach.body}
          </pre>
          <p className="mt-1.5 text-xs text-ink-muted">
            This is the quotation request you approved, unchanged. Edit it in
            your email if you want to.
          </p>
        </div>

        {tooLongForALink ? (
          <p className="rounded-lg border border-blocked/30 bg-blocked/5 px-3.5 py-2.5 text-sm text-blocked">
            This message is too long to travel in a link without being cut
            short. Copy it instead and paste it into a new email.
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          {!tooLongForALink ? (
            <>
              <a
                href={gmailUrl(draft)}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-lg bg-ink px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-ink/90"
              >
                Open in Gmail
              </a>
              <a
                href={mailtoUrl(draft)}
                className="rounded-lg border border-line px-4 py-2.5 text-sm font-medium text-ink-soft transition-colors hover:border-ink-muted hover:text-ink"
              >
                Open in my email app
              </a>
            </>
          ) : null}
          <button
            type="button"
            onClick={copy}
            className="rounded-lg border border-line px-4 py-2.5 text-sm font-medium text-ink-soft transition-colors hover:border-ink-muted hover:text-ink"
          >
            {copied ? "Copied" : "Copy the message"}
          </button>
        </div>

        <p className="text-xs text-ink-muted">
          Nothing is sent from here. The message opens in your own email, under
          your own address, and goes only when you send it.
        </p>
      </div>
    </Card>
  );
}
