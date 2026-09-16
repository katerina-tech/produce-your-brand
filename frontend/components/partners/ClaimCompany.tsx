"use client";

import { useEffect, useState, useTransition } from "react";

import { Badge, Button, Card, CardHeader, Notice } from "@/components/ui";
import { loadClaimAction, startClaimAction, verifyClaimAction } from "@/lib/actions";
import type { ClaimStatus } from "@/lib/types";

/**
 * "This is my company" — proved by control of the website already on file.
 *
 * The badge in this directory says a named Berlin business confirmed what was
 * read from its site. That is worth something only if the business confirmed
 * it, so this panel is the whole difference between a directory anybody can
 * edit and one worth believing. For a while it was the former: the endpoint
 * that sets the badge asked for no account at all.
 *
 * The address is never typed by the claimer — it is derived from the website
 * the survey recorded from OpenStreetMap before anybody asked to claim
 * anything. Somebody who could name the URL would only be proving they control
 * *a* website.
 *
 * Nothing appears here for a signed-out visitor: the panel is for the owner of
 * a business, and an invitation to claim shown to everybody would mostly be
 * noise.
 */
export function ClaimCompany({ partnerId }: { partnerId: string }) {
  const [claim, setClaim] = useState<ClaimStatus | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [pending, startTransition] = useTransition();

  useEffect(() => {
    let cancelled = false;
    void loadClaimAction(partnerId).then((outcome) => {
      if (cancelled) return;
      if (outcome.claim) setClaim(outcome.claim);
    });
    return () => {
      cancelled = true;
    };
  }, [partnerId]);

  function begin() {
    startTransition(async () => {
      const outcome = await startClaimAction(partnerId);
      setError(outcome.error ?? "");
      if (outcome.claim) setClaim(outcome.claim);
    });
  }

  function check() {
    startTransition(async () => {
      const outcome = await verifyClaimAction(partnerId);
      setError(outcome.error ?? "");
      if (outcome.claim) setClaim(outcome.claim);
    });
  }

  // Signed out, or the panel could not load: nothing at all rather than an
  // invitation somebody cannot act on.
  if (!claim) return null;

  return (
    <Card>
      <CardHeader
        title={claim.state === "verified" ? "Your company" : "Is this your company?"}
        hint={
          claim.state === "verified"
            ? "You can confirm what this listing says about your business."
            : "Prove you run the website on file, and this listing becomes yours to correct."
        }
        aside={claim.state === "verified" ? <Badge tone="match">yours</Badge> : null}
      />

      <div className="space-y-4 px-5 py-4 sm:px-6">
        {claim.state === "verified" ? (
          <p className="text-sm text-ink-soft">
            This account speaks for {claim.partner_name}. Confirming the reading
            below marks it as the company&rsquo;s own word, which is the
            strongest thing this directory can say about a business.
          </p>
        ) : null}

        {claim.state !== "verified" && !claim.claimable ? (
          <Notice tone="neutral" title="Not claimable this way">
            {claim.reason}
          </Notice>
        ) : null}

        {claim.state === "none" && claim.claimable ? (
          <div>
            <p className="text-sm text-ink-soft">
              We will give you a token to publish on your own website. Nothing
              is sent to you, and nothing is sent to the company — the check is
              that the file appears where only somebody running the site could
              put it.
            </p>
            <Button className="mt-3" onClick={begin} disabled={pending}>
              {pending ? "Preparing…" : "This is my company"}
            </Button>
          </div>
        ) : null}

        {claim.state === "pending" && claim.token && claim.proof_url ? (
          <div className="space-y-3">
            <div>
              <p className="text-sm font-medium">1. Publish this file</p>
              <code className="mt-1.5 block break-all rounded-lg border border-line bg-canvas px-3.5 py-2.5 font-mono text-xs">
                {claim.proof_url}
              </code>
            </div>
            <div>
              <p className="text-sm font-medium">2. With exactly this content</p>
              <code className="mt-1.5 block break-all rounded-lg border border-line bg-canvas px-3.5 py-2.5 font-mono text-xs">
                {claim.token}
              </code>
              <button
                type="button"
                onClick={() => {
                  void navigator.clipboard?.writeText(claim.token ?? "");
                  setCopied(true);
                }}
                className="mt-1.5 text-xs text-accent underline underline-offset-4"
              >
                {copied ? "Copied" : "Copy the token"}
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-3 border-t border-line pt-3">
              <Button onClick={check} disabled={pending}>
                {pending ? "Checking…" : "3. Check it"}
              </Button>
              {claim.expires_at ? (
                <p className="text-xs text-ink-muted">
                  This token stops working on {claim.expires_at.slice(0, 10)} —
                  so a claim nobody finishes cannot hold a listing for ever.
                </p>
              ) : null}
            </div>
          </div>
        ) : null}

        {claim.state === "pending" && !claim.token ? (
          <Notice tone="neutral" title="Being claimed">
            {claim.reason || "Another account is proving it runs this company."}
          </Notice>
        ) : null}

        {error ? (
          <Notice tone="error" title="Not yet">
            {error}
          </Notice>
        ) : null}
      </div>
    </Card>
  );
}
