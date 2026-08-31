"use client";

import { useState, useTransition } from "react";

import { Button, Card, CardHeader, Notice } from "@/components/ui";
import { submitFeedbackAction } from "@/lib/actions";
import type { AlternativeApproach, FoundUseful } from "@/lib/types";

/**
 * The product-validation instrumentation from the first customer-discovery
 * interview - see the README's Product hypothesis section. This is not a
 * feature the product needs to function; it exists so real usage produces
 * evidence for or against the core hypothesis, instead of an assumption.
 *
 * Deliberately not gated to a specific stage: whoever renders this decides
 * when it makes sense to ask (today: once a project completes).
 */

const FOUND_USEFUL_OPTIONS: { value: FoundUseful; label: string }[] = [
  { value: "yes", label: "Yes" },
  { value: "partly", label: "Partly" },
  { value: "no", label: "No" },
];

const ALTERNATIVE_OPTIONS: { value: AlternativeApproach; label: string }[] = [
  { value: "google", label: "Google" },
  { value: "chatgpt", label: "ChatGPT" },
  { value: "existing_platform", label: "An existing printing platform" },
  { value: "known_supplier", label: "A supplier I already know" },
  { value: "other", label: "Something else" },
];

export function FeedbackSurvey({ projectId }: { projectId: string }) {
  const [foundUseful, setFoundUseful] = useState<FoundUseful | null>(null);
  const [wouldContact, setWouldContact] = useState<boolean | null>(null);
  const [alternative, setAlternative] = useState<AlternativeApproach | "">("");
  const [missing, setMissing] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  if (submitted) {
    return (
      <Card>
        <div className="px-5 py-6 text-sm text-ink-soft sm:px-6">
          Thanks - that helps us validate whether this is actually useful.
        </div>
      </Card>
    );
  }

  const canSubmit = foundUseful !== null && wouldContact !== null && alternative !== "";

  const submit = () => {
    if (!canSubmit) return;
    setError(null);
    startTransition(async () => {
      const result = await submitFeedbackAction(projectId, {
        found_useful: foundUseful as FoundUseful,
        would_contact_supplier: wouldContact as boolean,
        alternative_approach: alternative as AlternativeApproach,
        missing: missing.trim() || undefined,
      });
      if (result.error) {
        setError(result.error);
      } else {
        setSubmitted(true);
      }
    });
  };

  return (
    <Card>
      <CardHeader
        title="Quick question"
        hint="Helps us learn whether this is actually useful - not required, and it doesn't affect your project."
      />
      <div className="space-y-5 px-5 py-5 sm:px-6">
        <fieldset>
          <legend className="eyebrow mb-2">
            Did this help you find a production option you could not easily find yourself?
          </legend>
          <div className="flex flex-wrap gap-2">
            {FOUND_USEFUL_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setFoundUseful(option.value)}
                className={`rounded-lg border px-3.5 py-2 text-sm font-medium transition-colors ${
                  foundUseful === option.value
                    ? "border-accent bg-accent text-white"
                    : "border-line-strong bg-surface text-ink hover:bg-canvas"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend className="eyebrow mb-2">Would you contact this supplier?</legend>
          <div className="flex flex-wrap gap-2">
            {[
              { value: true, label: "Yes" },
              { value: false, label: "No" },
            ].map((option) => (
              <button
                key={String(option.value)}
                type="button"
                onClick={() => setWouldContact(option.value)}
                className={`rounded-lg border px-3.5 py-2 text-sm font-medium transition-colors ${
                  wouldContact === option.value
                    ? "border-accent bg-accent text-white"
                    : "border-line-strong bg-surface text-ink hover:bg-canvas"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </fieldset>

        <div>
          <label htmlFor="alternative" className="eyebrow mb-2 block">
            How would you normally solve this?
          </label>
          <select
            id="alternative"
            value={alternative}
            onChange={(event) => setAlternative(event.target.value as AlternativeApproach)}
            className="w-full max-w-sm rounded-lg border border-line-strong bg-surface px-3 py-2 text-sm focus:border-accent focus:outline-none"
          >
            <option value="">Choose one…</option>
            {ALTERNATIVE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="missing" className="eyebrow mb-2 block">
            What was missing? (optional)
          </label>
          <textarea
            id="missing"
            rows={2}
            value={missing}
            onChange={(event) => setMissing(event.target.value)}
            placeholder="Anything that would have made this more useful"
            className="w-full resize-y rounded-lg border border-line-strong bg-surface px-3.5 py-2.5 text-sm leading-relaxed placeholder:text-ink-muted focus:border-accent focus:outline-none"
          />
        </div>

        {error ? <Notice tone="error">{error}</Notice> : null}

        <div className="flex justify-end">
          <Button onClick={submit} disabled={!canSubmit || pending}>
            {pending ? "Sending…" : "Send"}
          </Button>
        </div>
      </div>
    </Card>
  );
}
