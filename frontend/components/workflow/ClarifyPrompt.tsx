"use client";

import { useActionState } from "react";

import { Button, Card, CardHeader, Notice } from "@/components/ui";
import { answerClarification } from "@/lib/actions";
import type { ActionResult } from "@/lib/actions";
import type { StagePayload } from "@/lib/types";

/**
 * One question, one field.
 *
 * Which field is asked about is decided server-side by the completeness check;
 * this screen only renders it. That is why there is no form here - a form would
 * be the thing this product exists to replace.
 */
export function ClarifyPrompt({
  projectId,
  payload,
}: {
  projectId: string;
  payload: StagePayload;
}) {
  const [state, formAction, pending] = useActionState<ActionResult, FormData>(
    answerClarification.bind(null, projectId),
    {},
  );

  return (
    <Card>
      <CardHeader
        title="One quick question"
        hint="The agent needs this before it can recommend a production method."
      />
      <div className="space-y-4 px-5 py-5 sm:px-6">
        <p className="text-[15px] leading-relaxed">{payload.question}</p>

        {payload.reason ? (
          <p className="border-l-2 border-line-strong pl-3 text-sm text-ink-soft">
            {payload.reason}
          </p>
        ) : null}

        <form action={formAction} className="space-y-4">
          <label htmlFor="answer" className="sr-only">
            Your answer
          </label>
          <textarea
            id="answer"
            name="answer"
            rows={3}
            required
            placeholder="Type your answer…"
            className="w-full resize-y rounded-lg border border-line-strong bg-surface px-3.5 py-3 text-sm leading-relaxed placeholder:text-ink-muted focus:border-ink focus:outline-none"
          />

          {state.error ? <Notice tone="error">{state.error}</Notice> : null}

          <div className="flex justify-end">
            <Button type="submit" disabled={pending}>
              {pending ? "Updating the brief…" : "Send answer"}
            </Button>
          </div>
        </form>
      </div>
    </Card>
  );
}
