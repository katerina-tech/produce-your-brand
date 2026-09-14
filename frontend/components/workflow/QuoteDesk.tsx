"use client";

import { useState, useTransition } from "react";

import { Badge, Card, CardHeader, Notice } from "@/components/ui";
import { captureQuoteAction, deleteQuoteAction } from "@/lib/actions";
import type { ComparisonRow, Quote, QuoteDesk as Desk } from "@/lib/types";

/**
 * What happens after the request goes out.
 *
 * A supplier answers in prose, in German, hedged, and answers only some of what
 * was asked. This turns that letter into figures - and shows, beside every
 * figure, the words it was read from. That is the feature: a price you can
 * check in one glance against the sentence it came from is a price you can act
 * on, and one you cannot check is a rumour with a euro sign.
 *
 * Nothing here ranks suppliers. The table names cheapest and fastest when those
 * are defensible and stays quiet when they are not, because a column that
 * silently totals a net price against a gross one produces a number that looks
 * authoritative and is wrong.
 */

const EXAMPLE =
  "Machbar, aber bei 100 Stück kommen wir auf 14 Tage. Siebdruck geht nicht auf PVC, " +
  "wir würden Transferdruck vorschlagen. Preis ca. 8,50/Stück netto.";

function euros(value: number | null): string {
  return value === null
    ? "—"
    : new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" }).format(value);
}

/** One figure, with the supplier's own words underneath it. */
function Figure({
  label,
  value,
  source,
  corrected,
}: {
  label: string;
  value: string;
  source?: string;
  corrected?: boolean;
}) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-0.5 text-sm font-medium tabular">
        {value}
        {corrected ? (
          <span className="ml-2 text-xs font-normal text-ink-muted">(you corrected this)</span>
        ) : null}
      </p>
      {source ? (
        <p className="mt-0.5 text-xs italic text-ink-muted">&ldquo;{source}&rdquo;</p>
      ) : null}
    </div>
  );
}

function QuoteCard({
  projectId,
  quote,
  onChanged,
}: {
  projectId: string;
  quote: Quote;
  onChanged: (desk: Desk) => void;
}) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const sourceFor = (field: string) =>
    quote.evidence.find((item) => item.field === field)?.quote;
  const wasCorrected = (field: string) => quote.corrected_fields.includes(field);

  function remove() {
    startTransition(async () => {
      const result = await deleteQuoteAction(projectId, quote.id);
      if (result.error) setError(result.error);
      else if (result.desk) onChanged(result.desk);
    });
  }

  return (
    <div className="border-b border-line px-5 py-5 last:border-0 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">{quote.supplier_name}</p>
          <p className="mt-0.5 text-xs text-ink-muted">Received {quote.received_on}</p>
        </div>
        <div className="flex items-center gap-2">
          {quote.feasible === true ? <Badge tone="match">Says it is feasible</Badge> : null}
          {quote.feasible === null ? <Badge tone="neutral">Feasibility unclear</Badge> : null}
          {quote.confirmed_by_human ? <Badge tone="neutral">You checked this</Badge> : null}
          <button
            type="button"
            onClick={remove}
            disabled={pending}
            className="text-xs text-ink-muted underline underline-offset-4 hover:text-ink"
          >
            Remove
          </button>
        </div>
      </div>

      {quote.needs_manual_entry ? (
        <Notice tone="warning" title="Nothing could be read from this reply">
          The text is kept below so nothing is lost. The figures have to be typed
          in by hand.
        </Notice>
      ) : null}

      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Figure
          label="Unit price"
          value={
            quote.unit_price_eur === null
              ? "not quoted"
              : `${euros(quote.unit_price_eur)}${quote.price_is_estimate ? " (estimate)" : ""}`
          }
          source={sourceFor("unit_price_eur")}
          corrected={wasCorrected("unit_price_eur")}
        />
        <Figure
          label="For a quantity of"
          value={quote.quoted_quantity === null ? "not stated" : String(quote.quoted_quantity)}
          source={sourceFor("quoted_quantity")}
          corrected={wasCorrected("quoted_quantity")}
        />
        <Figure
          label="Lead time"
          value={quote.lead_time_days === null ? "not stated" : `${quote.lead_time_days} days`}
          source={sourceFor("lead_time_days")}
          corrected={wasCorrected("lead_time_days")}
        />
        <Figure
          label="Price basis"
          value={quote.price_basis === "unstated" ? "not stated" : quote.price_basis}
          source={sourceFor("price_basis")}
          corrected={wasCorrected("price_basis")}
        />
      </div>

      {quote.proposed_method ? (
        <p className="mt-4 text-sm text-ink-soft">
          Proposes <strong className="font-medium text-ink">{quote.proposed_method.replace(/_/g, " ")}</strong>{" "}
          instead
          {sourceFor("proposed_method") ? (
            <span className="italic text-ink-muted"> &mdash; &ldquo;{sourceFor("proposed_method")}&rdquo;</span>
          ) : null}
        </p>
      ) : null}

      {quote.unverified_fields.length > 0 ? (
        <p className="mt-4 rounded-lg border border-blocked/30 bg-blocked/5 px-3.5 py-2.5 text-xs text-blocked">
          Discarded as unsupported: {quote.unverified_fields.join(", ")}. The
          reading did not match anything in the reply, so it was deleted rather
          than shown.
        </p>
      ) : null}

      {error ? <p className="mt-3 text-xs text-blocked">{error}</p> : null}

      <details className="mt-4">
        <summary className="cursor-pointer text-xs text-ink-muted hover:text-ink">
          The reply, as received
        </summary>
        <pre className="mt-2 whitespace-pre-wrap rounded-lg border border-line bg-canvas px-3.5 py-3 font-sans text-sm leading-relaxed text-ink-soft">
          {quote.source_text}
        </pre>
      </details>
    </div>
  );
}

function ComparisonTable({ desk }: { desk: Desk }) {
  if (desk.rows.length < 2) return null;

  return (
    <div className="border-t border-line px-5 py-5 sm:px-6">
      <h3 className="text-sm font-semibold">Side by side</h3>
      <p className="mt-1 text-xs text-ink-muted">{desk.note}</p>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-ink-muted">
              <th className="pb-2 pr-4 font-medium">Supplier</th>
              <th className="pb-2 pr-4 font-medium">Total</th>
              <th className="pb-2 pr-4 font-medium">Lead time</th>
              <th className="pb-2 font-medium">Answered</th>
            </tr>
          </thead>
          <tbody>
            {desk.rows.map((row: ComparisonRow) => (
              <tr key={row.quote_id} className="border-b border-line last:border-0 align-top">
                <td className="py-3 pr-4">
                  {row.supplier_name}
                  {row.quote_id === desk.cheapest_quote_id ? (
                    <Badge tone="match">Cheapest</Badge>
                  ) : null}
                  {row.quote_id === desk.fastest_quote_id ? (
                    <Badge tone="neutral">Fastest</Badge>
                  ) : null}
                </td>
                <td className="py-3 pr-4 tabular">
                  {row.comparable_total_eur !== null ? (
                    euros(row.comparable_total_eur)
                  ) : (
                    /* Never a bare blank: an empty money cell reads as
                       "expensive", which is a conclusion nobody established. */
                    <span className="text-xs text-ink-muted">
                      {row.blockers.join("; ")}
                    </span>
                  )}
                </td>
                <td className="py-3 pr-4 tabular">
                  {row.lead_time_days === null ? "—" : `${row.lead_time_days} d`}
                </td>
                <td className="py-3 text-xs text-ink-muted">
                  {row.answered_count} of {row.answered_count + row.unanswered.length}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FollowUps({ desk }: { desk: Desk }) {
  if (desk.followups.length === 0) return null;

  return (
    <div className="border-t border-line px-5 py-5 sm:px-6">
      <h3 className="text-sm font-semibold">Still to ask</h3>
      <p className="mt-1 text-xs text-ink-muted">
        Carried out of your original request, word for word &mdash; a reminder
        rather than a new enquiry. Copy one into a reply when you are ready.
      </p>

      <div className="mt-3 space-y-4">
        {desk.followups.map((draft) => (
          <div key={draft.supplier_name} className="rounded-lg border border-line px-3.5 py-3">
            <p className="text-sm font-medium">{draft.supplier_name}</p>
            <p className="text-xs text-ink-muted">{draft.subject}</p>
            <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-ink-soft">
              {draft.questions.map((question) => (
                <li key={question}>{question}</li>
              ))}
              {draft.asks.map((ask) => (
                <li key={ask}>{ask}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

export function QuoteDeskPanel({
  projectId,
  initial,
}: {
  projectId: string;
  initial: Desk;
}) {
  const [desk, setDesk] = useState<Desk>(initial);
  const [reply, setReply] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function capture() {
    const text = reply.trim();
    if (!text) return;
    setError(null);
    startTransition(async () => {
      const result = await captureQuoteAction(projectId, text);
      if (result.error) {
        setError(result.error);
        return;
      }
      if (result.desk) {
        setDesk(result.desk);
        setReply("");
      }
    });
  }

  return (
    <Card>
      <CardHeader
        title="Replies from partners"
        hint="Paste a reply as it arrived. Every figure is shown with the words it was read from."
      />

      <div className="px-5 py-5 sm:px-6">
        <label htmlFor="supplier-reply" className="mb-1.5 block text-sm font-medium">
          Paste a supplier&rsquo;s reply
        </label>
        <textarea
          id="supplier-reply"
          rows={4}
          value={reply}
          onChange={(event) => setReply(event.target.value)}
          placeholder={EXAMPLE}
          className="w-full resize-y rounded-lg border border-line-strong bg-surface px-3.5 py-3 text-sm leading-relaxed placeholder:text-ink-muted focus:border-accent focus:outline-none"
        />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-ink-muted">
            The reply is screened before anything reads it, and a figure whose
            words are not in the text is deleted rather than shown.
          </p>
          <button
            type="button"
            onClick={capture}
            disabled={pending || reply.trim().length === 0}
            className="rounded-lg bg-ink px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-ink/90 disabled:opacity-50"
          >
            {pending ? "Reading…" : "Read this reply"}
          </button>
        </div>
        {error ? <p className="mt-3 text-sm text-blocked">{error}</p> : null}
      </div>

      {desk.quotes.length > 0 ? (
        <div className="border-t border-line">
          {desk.quotes.map((quote) => (
            <QuoteCard
              key={quote.id}
              projectId={projectId}
              quote={quote}
              onChanged={setDesk}
            />
          ))}
        </div>
      ) : null}

      <ComparisonTable desk={desk} />
      <FollowUps desk={desk} />
    </Card>
  );
}
