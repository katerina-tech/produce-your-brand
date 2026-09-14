import Link from "next/link";

import { Badge, Card, EmptyState, Notice } from "@/components/ui";
import { getHealth, listProjects } from "@/lib/api";
import { getAccount } from "@/lib/auth";
import { claimProjectAction } from "@/lib/actions";
import { STAGE_LABELS } from "@/lib/types";
import type { ProjectSummary } from "@/lib/types";

export const dynamic = "force-dynamic";

function formatUpdated(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
}

function ProjectRow({
  project,
  onKeep,
}: {
  project: ProjectSummary;
  /** Rendered only for a project nobody owns, and only when somebody is
   *  signed in to own it. */
  onKeep?: (formData: FormData) => Promise<void>;
}) {
  const isDone = project.stage === "completed";
  const needsAttention = project.stage === "failed";

  return (
    <li className="border-b border-line last:border-0">
      <div className="flex flex-wrap items-center gap-3 px-5 py-4 transition-colors hover:bg-canvas sm:px-6">
        <Link href={`/projects/${project.id}`} className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">
            {project.product ?? "Untitled project"}
          </p>
          <p className="mt-0.5 text-xs text-ink-muted">
            {project.quantity !== null ? (
              <span className="tabular">{project.quantity} units · </span>
            ) : null}
            updated {formatUpdated(project.updated_at)}
          </p>
        </Link>

        {onKeep ? (
          <form action={onKeep}>
            <input type="hidden" name="projectId" value={project.id} />
            <button
              type="submit"
              className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-ink-soft transition-colors hover:border-ink-muted hover:text-ink"
            >
              Keep
            </button>
          </form>
        ) : null}

        <Badge tone={isDone ? "match" : needsAttention ? "mismatch" : "neutral"}>
          {STAGE_LABELS[project.stage]}
        </Badge>
      </div>
    </li>
  );
}

export default async function DashboardPage() {
  const [projects, health, account] = await Promise.all([
    listProjects().catch(() => null),
    getHealth(),
    getAccount(),
  ]);

  /**
   * Take ownership of a project nobody owns.
   *
   * The failure worth thinking about is a race - somebody else claimed it in
   * between - and it needs no message: the project simply stops appearing,
   * which says what happened more plainly than a banner would.
   */
  async function keep(formData: FormData) {
    "use server";
    await claimProjectAction(String(formData.get("projectId") ?? ""));
  }

  const mine = projects?.filter((project) => project.mine) ?? [];
  const unowned = projects?.filter((project) => !project.mine) ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
        <p className="mt-1.5 text-sm text-ink-soft">
          Describe what you want to customise. The agent works out how it can be
          made and who can make it — you approve every step.
        </p>
      </div>

      {projects === null ? (
        <Notice tone="error" title="The API is not reachable">
          Start the backend on port 8000:{" "}
          <code className="font-mono text-xs">
            cd backend &amp;&amp; uv run python -m uvicorn app.main:app --port 8000
          </code>
        </Notice>
      ) : null}

      {health && health.status === "degraded" ? (
        <Notice tone="warning" title="The backend is running but not fully configured">
          {!health.checks.api_key_configured
            ? "No model API key is configured, so requirement extraction will fail. Set OPENAI_API_KEY in .env."
            : "Some readiness checks did not pass. See /api/health for detail."}
        </Notice>
      ) : null}

      {mine.length > 0 ? (
        <section>
          <h2 className="mb-2 text-sm font-semibold">Your projects</h2>
          <Card>
            <ul>
              {mine.map((project) => (
                <ProjectRow key={project.id} project={project} />
              ))}
            </ul>
          </Card>
          <p className="mt-2 text-xs text-ink-muted">
            Private to {account?.email}. Nobody else can open these, with or
            without the link.
          </p>
        </section>
      ) : null}

      {unowned.length > 0 ? (
        <section>
          {account ? (
            <>
              <h2 className="mb-2 text-sm font-semibold">Started without an account</h2>
              <Card>
                <ul>
                  {unowned.map((project) => (
                    <ProjectRow key={project.id} project={project} onKeep={keep} />
                  ))}
                </ul>
              </Card>
              <p className="mt-2 text-xs text-ink-muted">
                Open to anyone with the link. <strong>Keep</strong> moves one onto
                your account and closes it to everybody else.
              </p>
            </>
          ) : (
            <>
              <Card>
                <ul>
                  {unowned.map((project) => (
                    <ProjectRow key={project.id} project={project} />
                  ))}
                </ul>
              </Card>
              <p className="mt-2 text-xs text-ink-muted">
                These are open to anyone with the link.{" "}
                <Link
                  href="/account"
                  className="text-accent underline underline-offset-4"
                >
                  Sign in
                </Link>{" "}
                to keep a project to yourself — everything works either way.
              </p>
            </>
          )}
        </section>
      ) : null}

      {projects && projects.length === 0 ? (
        <EmptyState
          title="No projects yet"
          body="Start by describing a job in plain language — for example, a batch of products you already own that needs your logo applied."
          action={
            <Link
              href="/new"
              className="inline-flex rounded-lg bg-ink px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-ink/90"
            >
              Start a project
            </Link>
          }
        />
      ) : null}

      {health ? (
        <p className="text-xs text-ink-muted">
          <span className="tabular">{health.checks.supplier_count}</span>{" "}
          production partners ·{" "}
          <span className="tabular">{health.checks.knowledge_doc_count}</span>{" "}
          knowledge documents ·{" "}
          {health.checks.search_index_built ? "index ready" : "index not built"}
        </p>
      ) : null}
    </div>
  );
}
