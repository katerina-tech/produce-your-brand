/**
 * The only place this app talks to the backend.
 *
 * Server-side only. The browser never holds the API base URL and never issues a
 * cross-origin request: reads happen in server components, writes go through
 * server actions. That keeps credentials and the API surface off the client and
 * makes CORS a non-problem rather than a configuration.
 */

import type { Health, ProjectState, ProjectSummary, ResumeAction } from "./types";

const BASE = process.env.API_BASE_URL ?? "http://127.0.0.1:8000/api";

/** A failure we can show a user, carrying the backend's own error code. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string = "unknown",
    readonly recoverable: boolean = true,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
      cache: "no-store",
    });
  } catch {
    // A dead backend is the most likely failure in development, so it gets a
    // message that says what to do rather than "fetch failed".
    throw new ApiError(
      "The API is not reachable. Start the backend on port 8000.",
      503,
      "api_unreachable",
      true,
    );
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const error = body?.error;
    throw new ApiError(
      error?.message ?? `Request failed with status ${response.status}.`,
      response.status,
      error?.code ?? `http_${response.status}`,
      error?.recoverable ?? response.status < 500,
    );
  }

  return (await response.json()) as T;
}

export async function getHealth(): Promise<Health | null> {
  try {
    return await request<Health>("/health");
  } catch {
    // The dashboard renders without it; a missing banner is better than a
    // blank page.
    return null;
  }
}

export async function listProjects(): Promise<ProjectSummary[]> {
  const body = await request<{ projects: ProjectSummary[] }>("/projects");
  return body.projects;
}

export async function getProject(id: string): Promise<ProjectState> {
  return request<ProjectState>(`/projects/${encodeURIComponent(id)}`);
}

export async function createProject(requestText: string): Promise<ProjectState> {
  return request<ProjectState>("/projects", {
    method: "POST",
    body: JSON.stringify({ request_text: requestText }),
  });
}

export async function resumeProject(
  id: string,
  action: ResumeAction,
  data: Record<string, unknown> = {},
): Promise<ProjectState> {
  return request<ProjectState>(`/projects/${encodeURIComponent(id)}/resume`, {
    method: "POST",
    body: JSON.stringify({ action, ...data }),
  });
}
