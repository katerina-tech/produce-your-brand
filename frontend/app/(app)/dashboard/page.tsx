import Link from "next/link";

import { Badge, Card, EmptyState, Notice } from "@/components/ui";
import { getHealth, listProjects } from "@/lib/api";
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

function ProjectRow({ project }: { project: ProjectSummary }) {
  const isDone = project.stage === "completed";
  const needsAttention = project.stage === "failed";

  return (
    <li className="border-b border-line last:border-0">
      <Link
        href={`/projects/${project.id}`}
        className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 transition-colors hover:bg-canvas sm:px-6"
      >
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">
            {project.product ?? "Untitled project"}
          </p>
          <p className="mt-0.5 text-xs text-ink-muted">
            {project.quantity !== null ? (
              <span className="tabular">{project.quantity} units · </span>
            ) : null}
            updated {formatUpdated(project.updated_at)}
          </p>
        </div>
        <Badge
          tone={isDone ? "match" : needsAttention ? "mismatch" : "neutral"}
        >
          {STAGE_LABELS[project.stage]}
        </Badge>
      </Link>
    </li>
  );
}

export default async function DashboardPage() {
  const [projects, health] = await Promise.all([
    listProjects().catch(() => null),
    getHealth(),
  ]);

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

      {projects && projects.length > 0 ? (
        <Card>
          <ul>
            {projects.map((project) => (
              <ProjectRow key={project.id} project={project} />
            ))}
          </ul>
        </Card>
      ) : projects ? (
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
