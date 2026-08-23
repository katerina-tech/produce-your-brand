"use client";

import { useState, useTransition } from "react";

import { Badge, Button, Card, CardHeader, Notice } from "@/components/ui";
import { approveRfq, editRfq } from "@/lib/actions";
import type { StagePayload } from "@/lib/types";
import { titleise } from "@/lib/types";

/**
 * Human gate 4: the RFQ.
 *
 * Editing is field-level rather than free-text, because the document structure
 * is assembled server-side and is not the user's to break. The confirmation
 * checklist is shown read-only for the same reason: an RFQ that quietly omits
 * "do you accept customer-owned goods" is worse than no RFQ.
 */
export function RfqReview({
  projectId,
  payload,
}: {
  projectId: string;
  payload: StagePayload;
}) {
  const rfq = payload.rfq;

  const [editing, setEditing] = useState(false);
  const [intro, setIntro] = useState(rfq?.intro ?? "");
  const [notes, setNotes] = useState((rfq?.additional_notes ?? []).join("\n"));
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  if (!rfq) {
    return <Notice tone="error">The quotation request could not be loaded.</Notice>;
  }

  const submit = (withEdits: boolean) => {
    setError(null);
    startTransition(async () => {
      const result = withEdits
        ? await editRfq(projectId, {
            ...rfq,
            intro,
            additional_notes: notes
              .split("\n")
              .map((line) => line.trim())
              .filter(Boolean),
            approved: false,
          })
        : await approveRfq(projectId);
      if (result.error) setError(result.error);
    });
  };

  return (
    <Card>
      <CardHeader
        title="Request for quotation"
        hint={`Addressed to ${rfq.supplier_name}. Nothing is sent — this is yours to keep or copy.`}
        aside={
          <Badge tone={rfq.approved ? "match" : "partial"}>
            {rfq.approved ? "Approved" : "Awaiting your approval"}
          </Badge>
        }
      />

      <div className="space-y-6 px-5 py-5 sm:px-6">
        <div>
          <h3 className="eyebrow">Opening</h3>
          {editing ? (
            <textarea
              value={intro}
              onChange={(event) => setIntro(event.target.value)}
              rows={3}
              className="mt-2 w-full resize-y rounded-lg border border-line-strong bg-surface px-3.5 py-2.5 text-sm leading-relaxed focus:border-ink focus:outline-none"
            />
          ) : (
            <p className="mt-2 text-sm leading-relaxed text-ink-soft">{intro}</p>
          )}
        </div>

        <div>
          <h3 className="eyebrow">Project</h3>
          <dl className="mt-2 divide-y divide-line text-sm">
            {(
              [
                ["Product", rfq.product_summary],
                ["Quantity", rfq.quantity === null ? "Not specified" : String(rfq.quantity)],
                [
                  "Customer supplies the product",
                  rfq.customer_supplies_product === null
                    ? "Not specified"
                    : rfq.customer_supplies_product
                      ? "Yes"
                      : "No",
                ],
                ["Customisation", rfq.customization],
                ["Preferred method", titleise(rfq.preferred_method)],
                ["Design", rfq.design_status],
                ["Deadline", rfq.deadline ?? "Not specified"],
                ["Delivery", rfq.delivery_location ?? "Not specified"],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="flex gap-4 py-2">
                <dt className="w-56 shrink-0 text-ink-muted">{label}</dt>
                <dd className="text-ink">{value}</dd>
              </div>
            ))}
          </dl>
        </div>

        <div>
          <h3 className="eyebrow">Questions for the partner</h3>
          <ol className="mt-2 space-y-1.5 text-sm text-ink-soft">
            {rfq.confirmations_requested.map((item, index) => (
              <li key={item} className="flex gap-2.5">
                <span className="tabular w-4 shrink-0 text-ink-muted">
                  {index + 1}.
                </span>
                <span>{item}</span>
              </li>
            ))}
          </ol>
        </div>

        <div>
          <h3 className="eyebrow">Notes</h3>
          {editing ? (
            <textarea
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              rows={4}
              placeholder="One note per line"
              className="mt-2 w-full resize-y rounded-lg border border-line-strong bg-surface px-3.5 py-2.5 text-sm leading-relaxed placeholder:text-ink-muted focus:border-ink focus:outline-none"
            />
          ) : rfq.additional_notes.length > 0 ? (
            <ul className="mt-2 space-y-1 text-sm text-ink-soft">
              {rfq.additional_notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm italic text-ink-muted">None</p>
          )}
        </div>
      </div>

      {error ? (
        <div className="px-5 pb-4 sm:px-6">
          <Notice tone="error">{error}</Notice>
        </div>
      ) : null}

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-4 sm:px-6">
        <p className="text-xs text-ink-muted">
          Approving records your decision. It does not send anything.
        </p>
        <div className="flex gap-2">
          {editing ? (
            <>
              <Button tone="secondary" onClick={() => setEditing(false)} disabled={pending}>
                Cancel
              </Button>
              <Button onClick={() => submit(true)} disabled={pending}>
                {pending ? "Saving…" : "Save and approve"}
              </Button>
            </>
          ) : (
            <>
              <Button tone="secondary" onClick={() => setEditing(true)} disabled={pending}>
                Edit
              </Button>
              <Button onClick={() => submit(false)} disabled={pending}>
                {pending ? "Approving…" : "Approve"}
              </Button>
            </>
          )}
        </div>
      </footer>
    </Card>
  );
}
