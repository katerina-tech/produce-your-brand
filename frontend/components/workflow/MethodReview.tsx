"use client";

import { useState, useTransition } from "react";

import { Badge, Button, Card, CardHeader, Notice } from "@/components/ui";
import { confirmMethod } from "@/lib/actions";
import type { StagePayload } from "@/lib/types";
import { titleise } from "@/lib/types";

const CONFIDENCE_TONE = {
  high: "match",
  medium: "partial",
  low: "mismatch",
} as const;

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h3 className="eyebrow">{title}</h3>
      <ul className="mt-2 space-y-1.5">
        {items.map((item) => (
          <li key={item} className="flex gap-2 text-sm leading-relaxed text-ink-soft">
            <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-line-strong" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Human gate 2: the production method.
 *
 * Deliberately shows uncertainty as prominently as the recommendation. A
 * technical claim presented as a guarantee is the failure mode this screen
 * exists to avoid, so confidence, open questions and whether the knowledge base
 * was consulted are all on the page rather than buried.
 */
export function MethodReview({
  projectId,
  payload,
}: {
  projectId: string;
  payload: StagePayload;
}) {
  const recommendation = payload.recommendation;
  const options = payload.selectable_methods ?? [];

  const [choice, setChoice] = useState(recommendation?.primary ?? "");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  if (!recommendation) {
    return <Notice tone="error">No recommendation was produced.</Notice>;
  }

  const submit = () => {
    setError(null);
    startTransition(async () => {
      const result = await confirmMethod(projectId, choice);
      if (result.error) setError(result.error);
    });
  };

  const overriding = choice !== recommendation.primary;

  return (
    <Card>
      <CardHeader
        title="Recommended production method"
        hint="A recommendation, not a verified quote. The partner confirms feasibility."
        aside={
          <Badge tone={CONFIDENCE_TONE[recommendation.confidence]}>
            {titleise(recommendation.confidence)} confidence
          </Badge>
        }
      />

      <div className="space-y-6 px-5 py-5 sm:px-6">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <p className="text-xl font-semibold tracking-tight">
            {titleise(recommendation.primary)}
          </p>
          {recommendation.alternative ? (
            <p className="text-sm text-ink-soft">
              alternative: {titleise(recommendation.alternative)}
            </p>
          ) : null}
        </div>

        <p className="max-w-2xl text-[15px] leading-relaxed text-ink-soft">
          {recommendation.rationale}
        </p>

        <div className="grid gap-6 sm:grid-cols-2">
          <List title="Constraints" items={recommendation.constraints} />
          <List title="Artwork requirements" items={recommendation.artwork_requirements} />
        </div>

        {recommendation.open_questions.length > 0 ? (
          <Notice tone="warning" title="Still unverified">
            <ul className="mt-1 space-y-1">
              {recommendation.open_questions.map((question) => (
                <li key={question}>{question}</li>
              ))}
            </ul>
          </Notice>
        ) : null}

        <div className="rounded-lg border border-line bg-canvas px-4 py-3">
          <p className="eyebrow">Grounding</p>
          {recommendation.retrieval_used && recommendation.sources.length > 0 ? (
            <>
              <p className="mt-1 text-sm text-ink-soft">
                Based on {recommendation.sources.length} production knowledge
                document{recommendation.sources.length === 1 ? "" : "s"}:
              </p>
              <ul className="mt-2 space-y-1">
                {recommendation.sources.map((source) => (
                  <li key={source.title} className="text-sm">
                    {source.title}
                    {source.source ? (
                      <span className="text-ink-muted"> — {source.source}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="mt-1 text-sm text-ink-soft">
              No knowledge lookup was needed for this pairing, so the
              recommendation rests on general knowledge alone.
            </p>
          )}
        </div>

        <div className="border-t border-line pt-5">
          <label htmlFor="method" className="eyebrow">
            Method to proceed with
          </label>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <select
              id="method"
              value={choice}
              onChange={(event) => setChoice(event.target.value)}
              className="rounded-lg border border-line-strong bg-surface px-3 py-2 text-sm focus:border-ink focus:outline-none"
            >
              {options.map((option) => (
                <option key={option} value={option}>
                  {titleise(option)}
                  {option === recommendation.primary ? " (recommended)" : ""}
                </option>
              ))}
            </select>
            {overriding ? (
              <span className="text-xs text-partial">
                You are overriding the recommendation.
              </span>
            ) : null}
          </div>
        </div>
      </div>

      {error ? (
        <div className="px-5 pb-4 sm:px-6">
          <Notice tone="error">{error}</Notice>
        </div>
      ) : null}

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-4 sm:px-6">
        <p className="text-xs text-ink-muted">
          Partner matching starts only after you confirm the method.
        </p>
        <Button onClick={submit} disabled={pending || !choice}>
          {pending ? "Matching partners…" : "Confirm method"}
        </Button>
      </footer>
    </Card>
  );
}
