/**
 * Shared presentation primitives.
 *
 * Kept in one file because each is a handful of lines; splitting six tiny
 * components across six files buys nothing. Nothing here knows anything about
 * production, suppliers or scoring - they take props and render.
 */

import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

import type { Stage, Verdict } from "@/lib/types";
import { STAGE_LABELS, WORKFLOW_STAGES } from "@/lib/types";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-xl border border-line bg-surface ${className}`}
    >
      {children}
    </section>
  );
}

export function CardHeader({
  title,
  hint,
  aside,
}: {
  title: string;
  hint?: string;
  aside?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
      <div>
        <h2 className="text-base font-semibold tracking-tight">{title}</h2>
        {hint ? <p className="mt-1 text-sm text-ink-soft">{hint}</p> : null}
      </div>
      {aside}
    </header>
  );
}

type ButtonTone = "primary" | "secondary" | "quiet";

const BUTTON_TONES: Record<ButtonTone, string> = {
  primary:
    "bg-ink text-white hover:bg-ink/90 focus-visible:outline-accent disabled:bg-ink-muted",
  secondary:
    "border border-line-strong bg-surface text-ink hover:bg-canvas focus-visible:outline-accent",
  quiet: "text-ink-soft hover:text-ink hover:bg-canvas focus-visible:outline-accent",
};

export function Button({
  children,
  tone = "primary",
  type = "button",
  disabled,
  className = "",
  ...rest
}: {
  children: ReactNode;
  tone?: ButtonTone;
  type?: "button" | "submit";
  disabled?: boolean;
  className?: string;
} & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "className" | "type">) {
  return (
    <button
      type={type}
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed ${BUTTON_TONES[tone]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

const VERDICT_STYLES: Record<Verdict, { className: string; mark: string }> = {
  match: { className: "text-match bg-match-bg", mark: "✓" },
  partial: { className: "text-partial bg-partial-bg", mark: "~" },
  unknown: { className: "text-unknown bg-unknown-bg", mark: "?" },
  mismatch: { className: "text-mismatch bg-mismatch-bg", mark: "✕" },
};

export function VerdictMark({ verdict }: { verdict: Verdict }) {
  const style = VERDICT_STYLES[verdict];
  return (
    <span
      aria-label={verdict}
      className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-xs font-semibold ${style.className}`}
    >
      {style.mark}
    </span>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "match" | "partial" | "mismatch";
}) {
  const tones = {
    neutral: "bg-unknown-bg text-ink-soft border-line",
    match: "bg-match-bg text-match border-match/20",
    partial: "bg-partial-bg text-partial border-partial/20",
    mismatch: "bg-mismatch-bg text-mismatch border-mismatch/20",
  } as const;
  return (
    <span
      className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

/** A read-only field. `null` renders as an explicit gap, never as blank. */
export function Field({
  label,
  value,
}: {
  label: string;
  value: string | number | boolean | null | undefined;
}) {
  const isMissing = value === null || value === undefined || value === "";
  const display =
    typeof value === "boolean" ? (value ? "Yes" : "No") : String(value ?? "");

  return (
    <div className="border-b border-line py-3 last:border-0">
      <dt className="eyebrow">{label}</dt>
      <dd
        className={`mt-1 text-sm ${isMissing ? "italic text-ink-muted" : "text-ink"}`}
      >
        {isMissing ? "Not specified" : display}
      </dd>
    </div>
  );
}

export function ScoreBar({ score }: { score: number }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-line">
      <div
        className="h-full rounded-full bg-accent"
        style={{ width: `${Math.max(0, Math.min(100, score))}%` }}
      />
    </div>
  );
}

/** Where the project is. Purely derived from the stage the API reports. */
export function StageStepper({ current }: { current: Stage }) {
  const done = current === "completed";
  // Draft and clarification both sit before the first gate, so they read as
  // "working towards the brief" rather than leaving the stepper looking inert.
  const currentIndex =
    current === "draft" || current === "clarifying"
      ? 0
      : WORKFLOW_STAGES.indexOf(current);

  return (
    <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
      {WORKFLOW_STAGES.map((stage, index) => {
        const isDone = done || index < currentIndex;
        const isCurrent = !done && index === currentIndex;
        return (
          <li key={stage} className="flex items-center gap-2">
            {index > 0 ? (
              <span aria-hidden className="text-line-strong">
                /
              </span>
            ) : null}
            <span
              aria-current={isCurrent ? "step" : undefined}
              className={
                isCurrent
                  ? "font-semibold text-accent"
                  : isDone
                    ? "text-ink-soft"
                    : "text-ink-muted"
              }
            >
              {isDone ? "✓ " : ""}
              {STAGE_LABELS[stage]}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-dashed border-line-strong bg-surface px-6 py-14 text-center">
      <h2 className="text-base font-semibold">{title}</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-ink-soft">{body}</p>
      {action ? <div className="mt-6">{action}</div> : null}
    </div>
  );
}

export function Notice({
  tone = "neutral",
  title,
  children,
}: {
  tone?: "neutral" | "warning" | "error";
  title?: string;
  children: ReactNode;
}) {
  const tones = {
    neutral: "border-line bg-unknown-bg text-ink-soft",
    warning: "border-partial/25 bg-partial-bg text-partial",
    error: "border-mismatch/25 bg-mismatch-bg text-mismatch",
  } as const;
  return (
    <div className={`rounded-lg border px-4 py-3 text-sm ${tones[tone]}`}>
      {title ? <p className="font-semibold">{title}</p> : null}
      <div className={title ? "mt-1" : ""}>{children}</div>
    </div>
  );
}

/** Derives href from Link itself, so typedRoutes stays enforced here too. */
type Href = ComponentProps<typeof Link>["href"];

export function BackLink({ href, children }: { href: Href; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="text-sm text-ink-soft underline decoration-line-strong underline-offset-4 transition-colors hover:text-ink"
    >
      {children}
    </Link>
  );
}
