"use client";

import { useActionState, useRef, useState } from "react";

import { BackLink, Button, Card, CardHeader, Notice } from "@/components/ui";
import { DesignAttachment } from "@/components/DesignAttachment";
import { VoiceDictation } from "@/components/VoiceDictation";
import { startProject } from "@/lib/actions";
import { appendDictation } from "@/lib/dictation";
import type { ActionResult } from "@/lib/actions";

const EXAMPLE =
  "I have 100 black yoga mats made of PVC. I already own them. I want my gold logo added and need them in Berlin by September 15.";

export default function NewProjectPage() {
  const [state, formAction, pending] = useActionState<ActionResult, FormData>(
    startProject,
    {},
  );
  const [designUploadId, setDesignUploadId] = useState<string | null>(null);
  const request = useRef<HTMLTextAreaElement>(null);

  /**
   * Put a dictated phrase into the box.
   *
   * Written through the ref rather than by making the textarea controlled:
   * the form reads its value from FormData on submit, and turning it into
   * React state would mean re-rendering the whole form on every keystroke to
   * buy nothing. Dictation appends to whatever is already there, so speaking
   * and typing can be mixed in either order.
   */
  function dictate(fragment: string) {
    const box = request.current;
    if (!box) return;
    box.value = appendDictation(box.value, fragment);
    box.scrollTop = box.scrollHeight;
  }

  return (
    <div className="space-y-6">
      <BackLink href="/dashboard">← All projects</BackLink>

      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          What do you want to produce?
        </h1>
        <p className="mt-1.5 max-w-2xl text-sm text-ink-soft">
          One paragraph in your own words is enough. Mention the product,
          quantity, what should be applied, whether you already own the goods,
          and where and when you need them — the agent will ask if something
          essential is missing.
        </p>
        <p className="mt-2 max-w-2xl text-sm text-ink-muted">
          Most useful for the requests a quick search doesn&apos;t answer:
          unusual materials, customer-owned goods, odd quantities, tight
          deadlines, or a combination of these.
        </p>
      </div>

      <Card>
        <CardHeader
          title="Project request"
          hint="No form to fill in. Write it as you would to a colleague."
        />
        <form action={formAction} className="space-y-5 px-5 py-5 sm:px-6">
          <label htmlFor="request_text" className="sr-only">
            Describe the job
          </label>
          <textarea
            ref={request}
            id="request_text"
            name="request_text"
            rows={6}
            required
            minLength={10}
            defaultValue=""
            placeholder={EXAMPLE}
            className="w-full resize-y rounded-lg border border-line-strong bg-surface px-3.5 py-3 text-sm leading-relaxed placeholder:text-ink-muted focus:border-accent focus:outline-none"
          />

          <VoiceDictation onText={dictate} label="Dictate your request" />

          <div className="border-t border-line pt-5">
            <DesignAttachment onChange={setDesignUploadId} />
            <input type="hidden" name="design_upload_id" value={designUploadId ?? ""} />
          </div>

          {state.error ? <Notice tone="error">{state.error}</Notice> : null}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-ink-muted">
              Your text is analysed, never executed as instructions.
            </p>
            <Button type="submit" disabled={pending}>
              {pending ? "Reading your request…" : "Continue"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
