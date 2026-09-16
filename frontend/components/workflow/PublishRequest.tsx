"use client";

import { useEffect, useState, useTransition } from "react";

import { Badge, Button, Card, CardHeader, Notice } from "@/components/ui";
import {
  loadPublicationAction,
  publishRequestAction,
  withdrawRequestAction,
} from "@/lib/actions";
import type { Publication, PublicRequest } from "@/lib/types";

/**
 * Publish this request so companies can find you - or take it down.
 *
 * The whole panel is built around one rule: **nothing is published that the
 * buyer has not read as public text.** The preview is not a mock-up, it is the
 * exact listing the board would show, built server-side by the same code that
 * would store it. So the decision a buyer makes here is a decision about
 * something they can see, not about a description of it.
 *
 * Two choices, and both defaults protect them. The budget is off unless ticked,
 * because what somebody will pay is the one fact that weakens their position in
 * every negotiation that follows. The note starts empty, because their brief was
 * written for this product and not for strangers.
 */
export function PublishRequest({ projectId }: { projectId: string }) {
  const [state, setState] = useState<Publication | null>(null);
  const [error, setError] = useState("");
  const [showBudget, setShowBudget] = useState(false);
  const [note, setNote] = useState("");
  const [pending, startTransition] = useTransition();

  useEffect(() => {
    let cancelled = false;
    void loadPublicationAction(projectId).then((outcome) => {
      if (cancelled) return;
      setError(outcome.error ?? "");
      if (outcome.publication) {
        setState(outcome.publication);
        setShowBudget(outcome.publication.published?.budget_eur != null);
        setNote(outcome.publication.published?.note ?? "");
      }
    });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  function publish() {
    startTransition(async () => {
      const outcome = await publishRequestAction(projectId, { show_budget: showBudget, note });
      setError(outcome.error ?? "");
      if (outcome.publication) setState(outcome.publication);
    });
  }

  function withdraw() {
    startTransition(async () => {
      const outcome = await withdrawRequestAction(projectId);
      setError(outcome.error ?? "");
      if (outcome.publication) setState(outcome.publication);
    });
  }

  // Nothing at all until publishing is possible. The panel appears the moment
  // the brief is confirmed - which is also the moment it is most useful, while
  // the buyer is still looking rather than already talking to somebody - and a
  // "you cannot do this yet" card on a draft project is noise, not guidance.
  if (!state || (!state.can_publish && !state.published)) return null;

  const live = state.published;
  const shown = live ?? state.preview;

  return (
    <Card>
      <CardHeader
        title={live ? "Listed on the public board" : "Let companies find you"}
        hint={
          live
            ? `Visible to anyone until ${live.expires_on}. No name, no address, no email.`
            : "Publish what you need, anonymously, so companies can come to you."
        }
        aside={live ? <Badge tone="match">live</Badge> : null}
      />

      <div className="space-y-4 px-5 py-4 sm:px-6">
        {shown ? (
          <div>
            <p className="mb-2 text-sm font-medium">
              {live ? "What companies see" : "What companies would see"}
            </p>
            <Preview listing={shown} />
            <p className="mt-2 text-xs text-ink-muted">
              This is the listing itself, not a mock-up of it. Your name, your
              email and your street address are not part of it and never will
              be — companies reply to you through this product, and you decide
              who to answer.
            </p>
          </div>
        ) : null}

        {state.can_publish ? (
          <div className="space-y-3 border-t border-line pt-4">
            <div>
              <label htmlFor="note" className="mb-1.5 block text-sm font-medium">
                Anything to add, in your own words
              </label>
              <textarea
                id="note"
                rows={2}
                maxLength={600}
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder="Logo as a vector file, matt finish preferred…"
                className="w-full resize-y rounded-lg border border-line bg-surface px-3.5 py-2.5 text-[15px] outline-none transition-colors focus:border-accent"
              />
              <p className="mt-1 text-xs text-ink-muted">
                Written for strangers, so nothing from your brief goes public
                unless you put it here.
              </p>
            </div>

            <label className="flex items-start gap-2 text-sm text-ink-soft">
              <input
                type="checkbox"
                checked={showBudget}
                onChange={(event) => setShowBudget(event.target.checked)}
                className="mt-0.5 h-4 w-4"
              />
              <span>
                Show my budget
                <span className="block text-xs text-ink-muted">
                  Off by default. It is the one figure that weakens your hand in
                  the negotiation that follows.
                </span>
              </span>
            </label>

            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={publish} disabled={pending}>
                {pending ? "Saving…" : live ? "Update the listing" : "Publish it"}
              </Button>
              {live ? (
                <Button tone="secondary" onClick={withdraw} disabled={pending}>
                  Take it down
                </Button>
              ) : null}
            </div>
          </div>
        ) : null}

        {error ? (
          <Notice tone="error" title="Not saved">
            {error}
          </Notice>
        ) : null}
      </div>
    </Card>
  );
}

/** The listing exactly as the board renders it. */
function Preview({ listing }: { listing: PublicRequest }) {
  return (
    <div className="rounded-lg border border-line bg-canvas px-4 py-3">
      <p className="text-[15px] font-semibold">
        {listing.quantity ? <span className="tabular">{listing.quantity}× </span> : null}
        {listing.product}
      </p>
      <p className="mt-0.5 text-xs text-ink-muted">
        {[listing.material, listing.city].filter(Boolean).join(" · ") || "no material or city stated"}
      </p>
      {listing.note ? (
        <p className="mt-2 text-sm leading-snug text-ink-soft">{listing.note}</p>
      ) : null}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-muted">
        {listing.customer_owns_product === true ? <span>their own goods</span> : null}
        {listing.method ? <span>{listing.method.replace(/_/g, " ")}</span> : null}
        {listing.deadline ? <span>needed by {listing.deadline}</span> : null}
        {listing.budget_eur ? (
          <span className="tabular">
            budget {listing.budget_eur.toLocaleString("en-GB", { maximumFractionDigits: 0 })} EUR
          </span>
        ) : (
          <span>budget not shown</span>
        )}
        <span>closes {listing.expires_on}</span>
      </div>
    </div>
  );
}
