"use client";

import { useActionState, useState } from "react";

import { Button, Card, CardHeader, Notice } from "@/components/ui";
import { answerClarification, restartRequest } from "@/lib/actions";
import type { ActionResult } from "@/lib/actions";
import type { StagePayload } from "@/lib/types";

/**
 * One question, one field.
 *
 * Which field is asked about is decided server-side by the completeness check;
 * this screen only renders it. That is why there is no form here - a form would
 * be the thing this product exists to replace.
 *
 * The one exception is the "edit the original request instead" path below: if
 * the question itself reveals a mistake or missing context in the original
 * description, answering it one field at a time is the wrong tool. That path
 * re-runs extraction on the new text server-side (see restart_request in
 * lib/actions.ts) - it is not a client-side rewind of anything.
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
  const [restartState, restartAction, restartPending] = useActionState<
    ActionResult,
    FormData
  >(restartRequest.bind(null, projectId), {});
  const [editingRequest, setEditingRequest] = useState(false);

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

        {!editingRequest ? (
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
              className="w-full resize-y rounded-lg border border-line-strong bg-surface px-3.5 py-3 text-sm leading-relaxed placeholder:text-ink-muted focus:border-accent focus:outline-none"
            />

            {state.error ? <Notice tone="error">{state.error}</Notice> : null}

            <div className="flex flex-wrap items-center justify-between gap-3">
              <button
                type="button"
                onClick={() => setEditingRequest(true)}
                className="text-sm text-ink-soft underline decoration-line-strong underline-offset-4 transition-colors hover:text-ink"
              >
                Something wrong above? Edit your original request instead
              </button>
              <Button type="submit" disabled={pending}>
                {pending ? "Updating the brief…" : "Send answer"}
              </Button>
            </div>
          </form>
        ) : (
          <form action={restartAction} className="space-y-4 border-t border-line pt-4">
            <div>
              <label htmlFor="raw_request" className="eyebrow">
                Your request
              </label>
              <p className="mt-1 text-sm text-ink-soft">
                This replaces your original description and starts extraction
                over from scratch - the question above goes away because the
                agent re-reads the whole thing.
              </p>
            </div>
            <textarea
              id="raw_request"
              name="raw_request"
              rows={5}
              required
              minLength={10}
              defaultValue={payload.raw_request ?? ""}
              className="w-full resize-y rounded-lg border border-line-strong bg-surface px-3.5 py-3 text-sm leading-relaxed placeholder:text-ink-muted focus:border-accent focus:outline-none"
            />

            {restartState.error ? <Notice tone="error">{restartState.error}</Notice> : null}

            <div className="flex justify-between gap-3">
              <Button
                tone="secondary"
                type="button"
                onClick={() => setEditingRequest(false)}
                disabled={restartPending}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={restartPending}>
                {restartPending ? "Restarting…" : "Restart with this description"}
              </Button>
            </div>
          </form>
        )}
      </div>
    </Card>
  );
}
