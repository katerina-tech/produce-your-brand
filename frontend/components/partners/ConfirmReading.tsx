"use client";

import { useState, useTransition } from "react";

import { Button, Notice } from "@/components/ui";
import { setVerificationAction } from "@/lib/actions";

/**
 * The one fact about a company that no amount of scraping can produce.
 *
 * A model read the page and a verifier deleted every claim whose words were not
 * on it. Neither of those is a person saying "yes, this is what they do" - and
 * until somebody does, a company here is a lead rather than a partner.
 *
 * Reversible on purpose: a confirmation made in error should be as easy to take
 * back as it was to give, or people stop giving it.
 */
export function ConfirmReading({
  partnerId,
  verified,
  hasClaims,
}: {
  partnerId: string;
  verified: boolean;
  hasClaims: boolean;
}) {
  const [confirmed, setConfirmed] = useState(verified);
  const [error, setError] = useState("");
  const [pending, startTransition] = useTransition();

  function toggle() {
    startTransition(async () => {
      const outcome = await setVerificationAction(partnerId, !confirmed);
      if (outcome.error) {
        setError(outcome.error);
        return;
      }
      setError("");
      setConfirmed(outcome.verified ?? !confirmed);
    });
  }

  return (
    <div className="space-y-3">
      {confirmed ? (
        <Notice tone="neutral" title="Confirmed by a person">
          Somebody read these claims and stands behind them. This company counts
          as a partner rather than a listing.
        </Notice>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button tone={confirmed ? "secondary" : "primary"} disabled={pending} onClick={toggle}>
          {pending
            ? "Saving…"
            : confirmed
              ? "Withdraw the confirmation"
              : "Confirm this reading is right"}
        </Button>
        {!confirmed && !hasClaims ? (
          <p className="text-xs text-ink-muted">
            There is nothing read from this company yet — confirming would say
            only that it exists, which the source already told us.
          </p>
        ) : null}
      </div>

      {error ? <Notice tone="error" title="Not saved">{error}</Notice> : null}
    </div>
  );
}
