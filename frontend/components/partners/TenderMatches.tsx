"use client";

import Link from "next/link";
import { useState, useTransition } from "react";

import { Badge, Button, Notice } from "@/components/ui";
import { matchTenderAction } from "@/lib/actions";
import type { CapabilityMatches } from "@/lib/types";

/**
 * Which companies in the directory say they can do this contract.
 *
 * The thing a tender aggregator structurally cannot do: the other side of the
 * market is already in the same database. A list of contracts is a commodity;
 * a contract beside four Berlin shops that each wrote, on their own website,
 * that they do this work is not.
 *
 * Run on a click rather than on page load. Each candidate costs a model call,
 * and a board where opening a notice quietly spends money on somebody browsing
 * would be a board nobody could afford to leave public.
 */
export function TenderMatches({ tenderId }: { tenderId: string }) {
  const [result, setResult] = useState<CapabilityMatches | null>(null);
  const [error, setError] = useState("");
  const [pending, startTransition] = useTransition();

  function run() {
    startTransition(async () => {
      const outcome = await matchTenderAction(tenderId);
      setError(outcome.error ?? "");
      setResult(outcome.matches ?? null);
    });
  }

  return (
    <div className="space-y-4">
      {!result && !pending ? (
        <div>
          <Button onClick={run} disabled={pending}>
            Find companies for this contract
          </Button>
          <p className="mt-2 text-xs text-ink-muted">
            Searched against what each company wrote about itself, then checked
            one by one. Every answer quotes the company&rsquo;s own words.
          </p>
        </div>
      ) : null}

      {pending ? <p className="text-sm text-ink-soft">Reading the companies…</p> : null}

      {error ? (
        <Notice tone="error" title="The search did not run">
          {error}
        </Notice>
      ) : null}

      {result && !pending ? <Matches result={result} /> : null}
    </div>
  );
}

function Matches({ result }: { result: CapabilityMatches }) {
  if (result.companies_indexed === 0) {
    return (
      <Notice tone="warning" title="No company websites have been read yet">
        {result.note}
      </Notice>
    );
  }

  if (result.matches.length === 0) {
    return (
      <Notice tone="neutral" title="Nothing close">
        None of the{" "}
        <span className="tabular">{result.companies_indexed}</span> companies
        read so far describes work like this.
      </Notice>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-ink-muted">
        Searched <span className="tabular">{result.companies_indexed}</span> companies
        {result.note ? ` — ${result.note}` : ""}
      </p>
      <ul className="space-y-2">
        {result.matches.map((match) => (
          <li
            key={match.partner_id}
            className="rounded-lg border border-line bg-surface px-4 py-3"
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <Link
                href={`/companies/${match.partner_id}`}
                className="text-[15px] font-semibold underline decoration-line-strong underline-offset-4 hover:text-accent"
              >
                {match.partner_name}
              </Link>
              {match.supported ? (
                <Badge tone="match">says it can</Badge>
              ) : match.can_do_it === false ? (
                <Badge tone="mismatch">says it cannot</Badge>
              ) : (
                <Badge tone="partial">unclear — worth asking</Badge>
              )}
            </div>
            {match.reason ? (
              <p className="mt-1.5 text-sm text-ink-soft">{match.reason}</p>
            ) : null}
            {match.quote && match.quote_verified ? (
              <blockquote className="mt-2 border-l-2 border-line-strong pl-3 text-sm italic text-ink-soft">
                “{match.quote}”
              </blockquote>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
