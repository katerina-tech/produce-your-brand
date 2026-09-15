"use client";

import Link from "next/link";
import { useState, useTransition } from "react";

import { Badge, Button, Notice } from "@/components/ui";
import { matchPartnersAction } from "@/lib/actions";
import type { CapabilityMatches } from "@/lib/types";

/**
 * Search the directory by what a company said it can do.
 *
 * Deliberately not the same box as the name-and-address filter above it. That
 * one answers "is there a print shop in Kreuzberg"; this one answers "who can
 * put a gold logo on PVC mats I already own" - a question no keyword search
 * over company names has ever been able to answer, because the words a buyer
 * uses and the words a Berlin print shop puts on its site are not the same
 * words.
 *
 * The three verdicts are kept apart on screen because they mean different
 * things to a person deciding who to write to. A confirmed match quotes the
 * company's own sentence. "Unclear" is the list worth a phone call, and
 * collapsing it into "no" would throw away the most useful half of the answer.
 */
export function CapabilitySearch() {
  const [result, setResult] = useState<CapabilityMatches | null>(null);
  const [error, setError] = useState("");
  const [asked, setAsked] = useState("");
  const [pending, startTransition] = useTransition();

  function run(formData: FormData) {
    const requirement = String(formData.get("requirement") ?? "");
    setAsked(requirement.trim());
    startTransition(async () => {
      const outcome = await matchPartnersAction(requirement);
      setError(outcome.error ?? "");
      setResult(outcome.matches ?? null);
    });
  }

  return (
    <div className="space-y-4">
      <form action={run} className="space-y-3">
        <div>
          <label htmlFor="requirement" className="mb-1.5 block text-sm font-medium">
            Describe the job, in your own words
          </label>
          <textarea
            id="requirement"
            name="requirement"
            rows={2}
            placeholder="A gold logo printed onto 100 PVC yoga mats I already own"
            className="w-full resize-y rounded-lg border border-line bg-surface px-3.5 py-2.5 text-[15px] outline-none transition-colors focus:border-accent"
          />
          <p className="mt-1.5 text-xs text-ink-muted">
            Searched against what each company wrote about itself, then checked
            one by one. Every answer quotes the company&rsquo;s own words.
          </p>
        </div>
        <Button type="submit" disabled={pending}>
          {pending ? "Reading the companies…" : "Find companies"}
        </Button>
      </form>

      {error ? <Notice tone="error" title="The search did not run">{error}</Notice> : null}

      {result && !pending ? (
        <MatchList result={result} asked={asked} />
      ) : null}
    </div>
  );
}

function MatchList({ result, asked }: { result: CapabilityMatches; asked: string }) {
  if (result.companies_indexed === 0) {
    return (
      <Notice tone="warning" title="No websites have been read yet">
        {result.note}
      </Notice>
    );
  }

  if (result.matches.length === 0) {
    return (
      <Notice tone="neutral" title="Nothing came back">
        Nothing among the{" "}
        <span className="tabular">{result.companies_indexed}</span> companies
        read so far is close to that. Try describing the material or the
        process rather than the finished product.
      </Notice>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-ink-muted">
        Searched <span className="tabular">{result.companies_indexed}</span>{" "}
        companies for <span className="text-ink-soft">“{asked}”</span>
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
                href={`/partners/${match.partner_id}`}
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
            ) : match.quote ? (
              // The verdict was demoted rather than the company dropped: all
              // that is established is that the quote could not be found in
              // what they wrote, which is a reason not to repeat it here.
              <p className="mt-2 text-xs text-ink-muted">
                The supporting quote could not be found in this company&rsquo;s
                claims, so it is not shown and the verdict is treated as
                unclear.
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
