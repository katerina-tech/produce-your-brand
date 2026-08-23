"use client";

import { useState, useTransition } from "react";

import {
  Badge,
  Button,
  Card,
  CardHeader,
  Notice,
  ScoreBar,
  VerdictMark,
} from "@/components/ui";
import { selectSupplier } from "@/lib/actions";
import type { MatchResult, StagePayload } from "@/lib/types";
import { titleise } from "@/lib/types";

/**
 * Human gate 3: the partner matches.
 *
 * The score breakdown is always available rather than hidden behind a tooltip,
 * because "why 92%?" is the question that decides whether a buyer trusts the
 * number. Every value shown here was computed server-side in plain Python; the
 * model only wrote the prose paragraph, and that is labelled as such.
 */
function MatchCard({
  match,
  rank,
  onSelect,
  pending,
}: {
  match: MatchResult;
  rank: number;
  onSelect: () => void;
  pending: boolean;
}) {
  const [open, setOpen] = useState(rank === 1);

  return (
    <li className="border-b border-line last:border-0">
      <div className="px-5 py-5 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h3 className="text-[15px] font-semibold">{match.supplier_name}</h3>
              <span className="text-xs text-ink-muted">{match.supplier_id}</span>
            </div>

            <div className="mt-3 flex items-center gap-3">
              <span className="tabular text-2xl font-semibold leading-none">
                {match.score.toFixed(0)}
                <span className="text-base font-normal text-ink-muted">%</span>
              </span>
              <div className="max-w-[14rem] flex-1">
                <ScoreBar score={match.score} />
              </div>
            </div>
          </div>

          <Button onClick={onSelect} disabled={pending} tone={rank === 1 ? "primary" : "secondary"}>
            {pending ? "Selecting…" : "Select partner"}
          </Button>
        </div>

        {match.risk_flags.length > 0 ? (
          <ul className="mt-4 space-y-1.5">
            {match.risk_flags.map((flag) => (
              <li key={flag} className="flex gap-2 text-sm text-partial">
                <span aria-hidden>⚠</span>
                <span>{flag}</span>
              </li>
            ))}
          </ul>
        ) : null}

        {match.ai_explanation ? (
          <p className="mt-4 border-l-2 border-line-strong pl-3 text-sm leading-relaxed text-ink-soft">
            {match.ai_explanation}
            <span className="mt-1 block text-xs text-ink-muted">
              Written by the model from the computed breakdown below. It cannot
              change the score.
            </span>
          </p>
        ) : null}

        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="mt-4 text-sm text-ink-soft underline decoration-line-strong underline-offset-4 transition-colors hover:text-ink"
        >
          {open ? "Hide score breakdown" : "Why this score?"}
        </button>

        {open ? (
          <table className="mt-3 w-full text-sm">
            <caption className="sr-only">
              Score breakdown for {match.supplier_name}
            </caption>
            <tbody>
              {match.factors.map((factor) => (
                <tr key={factor.factor} className="border-t border-line">
                  <td className="w-8 py-2 align-top">
                    <VerdictMark verdict={factor.verdict} />
                  </td>
                  <td className="py-2 pr-3 align-top font-medium">
                    {titleise(factor.factor)}
                  </td>
                  <td className="tabular w-20 py-2 pr-3 align-top text-ink-soft">
                    {factor.awarded}/{factor.max_points}
                  </td>
                  <td className="py-2 align-top text-ink-soft">
                    {factor.explanation}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </div>
    </li>
  );
}

export function MatchList({
  projectId,
  payload,
}: {
  projectId: string;
  payload: StagePayload;
}) {
  const matches = payload.matches ?? [];
  const candidateCount = payload.candidate_count;
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [, startTransition] = useTransition();

  const choose = (supplierId: string) => {
    setError(null);
    setPendingId(supplierId);
    startTransition(async () => {
      const result = await selectSupplier(projectId, supplierId);
      if (result.error) {
        setError(result.error);
        setPendingId(null);
      }
    });
  };

  if (matches.length === 0) {
    return (
      <Notice tone="warning" title="No eligible partners">
        {candidateCount
          ? `${candidateCount} partner(s) offer this method, but none met the hard requirements for this brief.`
          : "No partner in the dataset can perform this method for this product category."}{" "}
        Try a different production method, or adjust the brief.
      </Notice>
    );
  }

  return (
    <Card>
      <CardHeader
        title="Matched production partners"
        hint="Scores are calculated in code from stored partner capabilities, not generated by the model."
        aside={
          <Badge>
            {matches.length} of {candidateCount ?? matches.length} eligible
          </Badge>
        }
      />
      {error ? (
        <div className="px-5 pt-4 sm:px-6">
          <Notice tone="error">{error}</Notice>
        </div>
      ) : null}
      <ul>
        {matches.map((match, index) => (
          <MatchCard
            key={match.supplier_id}
            match={match}
            rank={index + 1}
            pending={pendingId === match.supplier_id}
            onSelect={() => choose(match.supplier_id)}
          />
        ))}
      </ul>
      <footer className="border-t border-line px-5 py-4 sm:px-6">
        <p className="text-xs text-ink-muted">
          Partner records in this build are synthetic. Selecting a partner
          generates a quotation request for your review — it does not contact
          anyone.
        </p>
      </footer>
    </Card>
  );
}
