"use client";

import { useState, useTransition } from "react";

import { Badge, Button, Card, CardHeader, Field, Notice } from "@/components/ui";
import { confirmBrief, editBrief } from "@/lib/actions";
import type { Requirement, StagePayload } from "@/lib/types";

/** Fields the user may edit here, in the order they read naturally. */
const EDITABLE: { key: keyof Requirement; type: "text" | "number" | "boolean" | "date" }[] = [
  { key: "product", type: "text" },
  { key: "material", type: "text" },
  { key: "quantity", type: "number" },
  { key: "customer_owns_product", type: "boolean" },
  { key: "customization_description", type: "text" },
  { key: "preferred_finish", type: "text" },
  { key: "deadline", type: "date" },
  { key: "location", type: "text" },
];

const FALLBACK_LABELS: Record<string, string> = {
  product: "Product",
  product_category: "Category",
  material: "Material",
  quantity: "Quantity",
  customer_owns_product: "Product source",
  customization_description: "Customisation",
  design_available: "Design",
  preferred_finish: "Preferred finish",
  deadline: "Deadline",
  location: "Delivery location",
  priority: "Priority",
  additional_constraints: "Additional constraints",
};

/**
 * Human gate 1: the extracted Production Brief.
 *
 * Read-only by default with an explicit edit mode. Unknown values are shown as
 * "Not specified" rather than hidden, because an honest gap is information the
 * user needs before approving.
 */
export function BriefReview({
  projectId,
  payload,
}: {
  projectId: string;
  payload: StagePayload;
}) {
  const requirement = payload.requirement;
  const labels = payload.field_labels ?? FALLBACK_LABELS;

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Requirement | null>(requirement ?? null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  if (!requirement || !draft) {
    return <Notice tone="error">The brief could not be loaded.</Notice>;
  }

  const label = (key: string) => labels[key] ?? FALLBACK_LABELS[key] ?? key;

  const submit = (confirmOnly: boolean) => {
    setError(null);
    startTransition(async () => {
      const result = confirmOnly
        ? await confirmBrief(projectId)
        : await editBrief(projectId, draft as unknown as Record<string, unknown>);
      if (result.error) setError(result.error);
      else setEditing(false);
    });
  };

  const update = (key: keyof Requirement, raw: string, type: string) => {
    setDraft((current) => {
      if (!current) return current;
      let value: string | number | boolean | null = raw === "" ? null : raw;
      if (type === "number") value = raw === "" ? null : Number(raw);
      if (type === "boolean") value = raw === "" ? null : raw === "true";
      return { ...current, [key]: value };
    });
  };

  const unknownCount = (payload.still_unknown ?? []).length;

  return (
    <Card>
      <CardHeader
        title="Production brief"
        hint="Extracted from your request. Check it before the agent goes further."
        aside={
          unknownCount > 0 ? (
            <Badge tone="partial">
              {unknownCount} field{unknownCount === 1 ? "" : "s"} not specified
            </Badge>
          ) : (
            <Badge tone="match">Complete</Badge>
          )
        }
      />

      <div className="px-5 py-2 sm:px-6">
        {editing ? (
          <div className="space-y-3 py-3">
            {EDITABLE.map(({ key, type }) => {
              const value = draft[key];
              return (
                <div key={key} className="grid gap-1.5 sm:grid-cols-[11rem_1fr] sm:items-center">
                  <label htmlFor={`f-${key}`} className="eyebrow">
                    {label(key)}
                  </label>
                  {type === "boolean" ? (
                    <select
                      id={`f-${key}`}
                      value={value === null || value === undefined ? "" : String(value)}
                      onChange={(event) => update(key, event.target.value, type)}
                      className="rounded-lg border border-line-strong bg-surface px-3 py-2 text-sm focus:border-ink focus:outline-none"
                    >
                      <option value="">Not specified</option>
                      <option value="true">I supply the product</option>
                      <option value="false">The partner sources it</option>
                    </select>
                  ) : (
                    <input
                      id={`f-${key}`}
                      type={type === "number" ? "number" : type === "date" ? "date" : "text"}
                      value={value === null || value === undefined ? "" : String(value)}
                      onChange={(event) => update(key, event.target.value, type)}
                      className="rounded-lg border border-line-strong bg-surface px-3 py-2 text-sm focus:border-ink focus:outline-none"
                    />
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <dl className="sm:grid sm:grid-cols-2 sm:gap-x-10">
            <Field label={label("product")} value={requirement.product} />
            <Field label={label("quantity")} value={requirement.quantity} />
            <Field label={label("material")} value={requirement.material} />
            <Field
              label={label("customer_owns_product")}
              value={
                requirement.customer_owns_product === null
                  ? null
                  : requirement.customer_owns_product
                    ? "Customer-owned"
                    : "Partner sources it"
              }
            />
            <Field
              label={label("customization_description")}
              value={requirement.customization_description}
            />
            <Field label={label("preferred_finish")} value={requirement.preferred_finish} />
            <Field label={label("deadline")} value={requirement.deadline} />
            <Field label={label("location")} value={requirement.location} />
          </dl>
        )}
      </div>

      {error ? (
        <div className="px-5 pb-4 sm:px-6">
          <Notice tone="error">{error}</Notice>
        </div>
      ) : null}

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-4 sm:px-6">
        <p className="text-xs text-ink-muted">
          Nothing proceeds until you confirm.
        </p>
        <div className="flex gap-2">
          {editing ? (
            <>
              <Button tone="secondary" onClick={() => setEditing(false)} disabled={pending}>
                Cancel
              </Button>
              <Button onClick={() => submit(false)} disabled={pending}>
                {pending ? "Saving…" : "Save and continue"}
              </Button>
            </>
          ) : (
            <>
              <Button tone="secondary" onClick={() => setEditing(true)} disabled={pending}>
                Edit
              </Button>
              <Button onClick={() => submit(true)} disabled={pending}>
                {pending ? "Working…" : "Confirm brief"}
              </Button>
            </>
          )}
        </div>
      </footer>
    </Card>
  );
}
