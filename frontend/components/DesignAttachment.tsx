"use client";

import { useState, useTransition } from "react";

import { generateDesignAction, uploadDesignAction } from "@/lib/actions";

import { Button, Notice } from "./ui";

type Mode = "upload" | "generate";

/**
 * Optional design attachment for a new project: upload a file, or describe one
 * and have it generated.
 *
 * Generation is the one feature in this product with a real per-image cost -
 * unlike every model call elsewhere, which produces a small structured object -
 * so the button says so rather than looking free. This component only ever
 * reports an `upload_id` upward; it holds no opinion about what happens next.
 *
 * An uploaded file is previewed entirely client-side via `URL.createObjectURL`,
 * so the browser never needs the server to echo bytes it already has. A
 * generated image is different: it exists only on the server until the
 * generate call returns, so that response is the one deliberate exception
 * where the API sends image bytes back at all - see `GeneratedDesign` in
 * `lib/types.ts`.
 */
export function DesignAttachment({
  onChange,
}: {
  onChange: (uploadId: string | null) => void;
}) {
  const [mode, setMode] = useState<Mode>("upload");
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const [fileName, setFileName] = useState<string | null>(null);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [previewDataUrl, setPreviewDataUrl] = useState<string | null>(null);
  const [attachedId, setAttachedId] = useState<string | null>(null);

  const clear = () => {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    setFileName(null);
    setObjectUrl(null);
    setPreviewDataUrl(null);
    setAttachedId(null);
    setError(null);
    onChange(null);
  };

  const handleFile = (file: File) => {
    setError(null);
    setFileName(file.name);
    setObjectUrl(file.type.startsWith("image/") ? URL.createObjectURL(file) : null);

    const formData = new FormData();
    formData.set("file", file);

    startTransition(async () => {
      const result = await uploadDesignAction(formData);
      if (result.error || !result.upload) {
        setError(result.error ?? "The upload failed.");
        setFileName(null);
        setObjectUrl(null);
        return;
      }
      setAttachedId(result.upload.upload_id);
      onChange(result.upload.upload_id);
    });
  };

  const handleGenerate = () => {
    setError(null);
    startTransition(async () => {
      const result = await generateDesignAction(prompt);
      if (result.error || !result.upload) {
        setError(result.error ?? "Generation failed.");
        return;
      }
      setPreviewDataUrl(result.previewDataUrl ?? null);
      setAttachedId(result.upload.upload_id);
      onChange(result.upload.upload_id);
    });
  };

  const hasAttachment = attachedId !== null;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="eyebrow">Design (optional)</span>
        {hasAttachment ? (
          <button
            type="button"
            onClick={clear}
            className="text-xs text-ink-soft underline decoration-line-strong underline-offset-4 hover:text-ink"
          >
            Remove
          </button>
        ) : null}
      </div>

      {!hasAttachment ? (
        <div className="flex gap-1 rounded-lg bg-canvas p-1 text-sm">
          {(
            [
              ["upload", "Upload a file"],
              ["generate", "Generate with AI"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => {
                setMode(value);
                setError(null);
              }}
              className={`flex-1 rounded-md px-3 py-1.5 font-medium transition-colors ${
                mode === value ? "bg-surface shadow-sm" : "text-ink-soft hover:text-ink"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      ) : null}

      {hasAttachment ? (
        <div className="flex items-center gap-3 rounded-lg border border-line bg-canvas p-3">
          {objectUrl || previewDataUrl ? (
            // A plain <img>, not next/image: the source is a blob: or data:
            // URL held only in memory, which next/image's loader/optimisation
            // pipeline is not built for.
            <img
              src={objectUrl ?? previewDataUrl ?? undefined}
              alt="Attached design preview"
              className="h-14 w-14 shrink-0 rounded object-cover"
            />
          ) : (
            <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded bg-line text-xs text-ink-muted">
              File
            </div>
          )}
          <p className="min-w-0 truncate text-sm text-ink-soft">
            {fileName ?? "Generated design attached"}
          </p>
        </div>
      ) : mode === "upload" ? (
        <label className="block cursor-pointer rounded-lg border border-dashed border-line-strong bg-canvas px-4 py-6 text-center text-sm text-ink-soft transition-colors hover:border-ink-muted">
          <input
            type="file"
            accept="image/png,image/jpeg,application/pdf"
            className="sr-only"
            disabled={pending}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) handleFile(file);
            }}
          />
          {pending ? "Uploading…" : "Click to choose a PNG, JPEG or PDF"}
        </label>
      ) : (
        <div className="space-y-2">
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={2}
            maxLength={500}
            placeholder="e.g. a minimalist gold star logo on a plain background"
            className="w-full resize-y rounded-lg border border-line-strong bg-surface px-3.5 py-2.5 text-sm leading-relaxed placeholder:text-ink-muted focus:border-accent focus:outline-none"
          />
          <div className="flex items-center justify-between">
            <p className="text-xs text-ink-muted">Costs about $0.04 per image.</p>
            <Button
              type="button"
              tone="secondary"
              disabled={pending || prompt.trim().length < 3}
              onClick={handleGenerate}
            >
              {pending ? "Generating…" : "Generate image"}
            </Button>
          </div>
        </div>
      )}

      {error ? <Notice tone="error">{error}</Notice> : null}
    </div>
  );
}
