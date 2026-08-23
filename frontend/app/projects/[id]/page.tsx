import Link from "next/link";
import { notFound } from "next/navigation";

import { BackLink, Card, CardHeader, Notice, StageStepper } from "@/components/ui";
import { BriefReview } from "@/components/workflow/BriefReview";
import { ClarifyPrompt } from "@/components/workflow/ClarifyPrompt";
import { MatchList } from "@/components/workflow/MatchList";
import { MethodReview } from "@/components/workflow/MethodReview";
import { RfqReview } from "@/components/workflow/RfqReview";
import { ApiError, getProject } from "@/lib/api";
import type { ProjectState } from "@/lib/types";
import { STAGE_LABELS } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * The workflow shell.
 *
 * This switch is the entire client-side workflow logic, and it is a switch on a
 * value the server produced. The frontend does not know which step follows
 * which, when a clarification is needed, or what makes a brief complete - it
 * renders the stage it is told and posts back the action the server said it
 * expects. That is what makes it replaceable without touching the agent.
 */
function StageView({ state }: { state: ProjectState }) {
  const { stage, payload, project_id: projectId } = state;

  if (!payload) {
    if (stage === "completed") {
      return (
        <Card>
          <CardHeader
            title="Project complete"
            hint="The quotation request was approved and saved."
          />
          <div className="px-5 py-6 text-sm text-ink-soft sm:px-6">
            <p>
              Your approval is recorded against this project. Nothing was sent to
              any partner — the request is yours to send when you choose.
            </p>
          </div>
        </Card>
      );
    }

    // A failed run already explains itself above; a second panel saying
    // "nothing to review" only adds noise to a page the user is already
    // puzzled by.
    if (stage === "failed") return null;

    return (
      <Notice tone="warning" title="Nothing to review">
        This project has no pending step.
      </Notice>
    );
  }

  switch (stage) {
    case "clarifying":
      return <ClarifyPrompt projectId={projectId} payload={payload} />;
    case "brief_review":
      return <BriefReview projectId={projectId} payload={payload} />;
    case "method_review":
      return <MethodReview projectId={projectId} payload={payload} />;
    case "supplier_selection":
      return <MatchList projectId={projectId} payload={payload} />;
    case "rfq_review":
      return <RfqReview projectId={projectId} payload={payload} />;
    default:
      return (
        <Notice tone="warning" title={STAGE_LABELS[stage]}>
          There is no step to complete at this stage.
        </Notice>
      );
  }
}

export default async function ProjectPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let state: ProjectState;
  try {
    state = await getProject(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <div className="space-y-6">
        <BackLink href="/">← All projects</BackLink>
        <Notice tone="error" title="Could not load the project">
          {error instanceof ApiError
            ? error.message
            : "An unexpected error occurred."}
        </Notice>
      </div>
    );
  }

  // The API carries the product at every stage; the payload only sometimes
  // does, which is why this does not read from the payload first.
  const product =
    state.product ??
    state.payload?.requirement?.product ??
    state.payload?.rfq?.product_summary;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <BackLink href="/">← All projects</BackLink>
        <StageStepper current={state.stage} />
      </div>

      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {product ?? "Production project"}
        </h1>
        <p className="mt-1.5 text-sm text-ink-soft">
          {STAGE_LABELS[state.stage]}
          {state.expected_action ? " · awaiting your decision" : ""}
        </p>
      </div>

      {state.errors.length > 0 ? (
        <Notice tone="error" title="This project stopped early">
          <ul className="space-y-1">
            {state.errors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
          <p className="mt-3 text-xs">
            Nothing was committed, so no partner was contacted and nothing was
            saved beyond this record. A generation failure is most often the
            model provider refusing the request — check{" "}
            <code className="font-mono">/api/health</code> and the backend log,
            then start a new project.
          </p>
          <p className="mt-3">
            <Link
              href="/new"
              className="font-medium underline decoration-mismatch/40 underline-offset-4"
            >
              Start a new project
            </Link>
          </p>
        </Notice>
      ) : null}

      <StageView state={state} />
    </div>
  );
}
