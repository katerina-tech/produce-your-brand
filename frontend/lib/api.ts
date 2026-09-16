/**
 * The only place this app talks to the backend.
 *
 * Server-side only. The browser never holds the API base URL and never issues a
 * cross-origin request: reads happen in server components, writes go through
 * server actions. That keeps credentials and the API surface off the client and
 * makes CORS a non-problem rather than a configuration.
 *
 * Every request carries the caller's session cookie, which is why ownership
 * needed no per-call wiring: identity crosses this seam in one place, so an
 * endpoint added later is authenticated by default rather than by remembering.
 */

import { sessionHeader } from "./auth";
import type {
  CapabilityMatches,
  ClaimStatus,
  FeedbackRequest,
  GeneratedDesign,
  Health,
  NearbyStudiosResponse,
  Outreach,
  Partner,
  PartnerDetail,
  PartnerDirectory,
  ProjectState,
  QuoteDesk,
  ProjectSummary,
  Publication,
  DemandBoard,
  ResumeAction,
  Tender,
  TenderBoard,
  UploadResponse,
} from "./types";

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

async function throwOnErrorResponse(response: Response): Promise<void> {
  if (response.ok) return;
  const body = await response.json().catch(() => null);
  const error = body?.error;
  throw new ApiError(
    error?.message ?? `Request failed with status ${response.status}.`,
    response.status,
    error?.code ?? `http_${response.status}`,
    error?.recoverable ?? response.status < 500,
  );
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(await sessionHeader()),
        ...init?.headers,
      },
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

  await throwOnErrorResponse(response);
  return (await response.json()) as T;
}

/**
 * A multipart POST, for the one endpoint that takes a file rather than JSON.
 * Deliberately not routed through {@link request}: setting a Content-Type
 * header manually on a multipart body strips the boundary fetch would
 * otherwise generate, so this leaves headers to fetch entirely.
 */
async function postFile<T>(path: string, file: File): Promise<T> {
  const body = new FormData();
  body.set("file", file);

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method: "POST",
      body,
      headers: await sessionHeader(),
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      "The API is not reachable. Start the backend on port 8000.",
      503,
      "api_unreachable",
      true,
    );
  }

  await throwOnErrorResponse(response);
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

/** Take ownership of a project that has none. */
export async function claimProject(id: string): Promise<ProjectState> {
  return request<ProjectState>(`/projects/${id}/claim`, { method: "POST" });
}

export async function getProject(id: string): Promise<ProjectState> {
  return request<ProjectState>(`/projects/${encodeURIComponent(id)}`);
}

export async function createProject(
  requestText: string,
  designUploadId?: string,
): Promise<ProjectState> {
  return request<ProjectState>("/projects", {
    method: "POST",
    body: JSON.stringify({
      request_text: requestText,
      ...(designUploadId ? { design_upload_id: designUploadId } : {}),
    }),
  });
}

/** Upload a design file. Metadata only comes back - the body is never echoed. */
export async function uploadDesign(file: File): Promise<UploadResponse> {
  return postFile<UploadResponse>("/uploads", file);
}

/**
 * Generate a design from a text prompt. The one call in this system with a
 * real per-image cost - see the README's Design attachment section.
 */
export async function generateDesign(prompt: string): Promise<GeneratedDesign> {
  return request<GeneratedDesign>("/designs/generate", {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
}

/**
 * Real, unscored OpenStreetMap leads for this project's confirmed method.
 * Never merged with `matches` client-side - see NearbyStudio in ./types.
 */
export async function submitFeedback(id: string, feedback: FeedbackRequest): Promise<void> {
  await request<{ status: string }>(`/projects/${encodeURIComponent(id)}/feedback`, {
    method: "POST",
    body: JSON.stringify(feedback),
  });
}

/**
 * The approved quotation request, rendered as an email.
 *
 * Returns null when there is nothing to send yet - a project mid-workflow
 * answers 409, which is an ordinary state here and not worth an error screen.
 */
export async function getOutreach(id: string): Promise<Outreach | null> {
  try {
    return await request<Outreach>(`/projects/${id}/outreach`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) return null;
    throw error;
  }
}

/** The directory of real businesses. Filtering happens on the server. */
export async function getPartners(options: {
  q?: string;
  borough?: string;
  category?: string;
  withEmail?: boolean;
  limit?: number;
} = {}): Promise<PartnerDirectory> {
  const query = new URLSearchParams();
  if (options.q) query.set("q", options.q);
  if (options.borough) query.set("borough", options.borough);
  if (options.category) query.set("category", options.category);
  if (options.withEmail) query.set("with_email", "true");
  if (options.limit) query.set("limit", String(options.limit));
  const suffix = query.toString();
  return request<PartnerDirectory>(`/partners${suffix ? `?${suffix}` : ""}`);
}

/**
 * One company and what its own website says it does.
 *
 * The id carries a slash ("node/6532305050"), so it goes into the path as-is
 * behind an endpoint whose last segment is greedy. Encoding it would turn the
 * slash into %2F, which proxies are entitled to normalise back and some reject
 * outright.
 */
export async function getPartnerDetail(id: string): Promise<PartnerDetail | null> {
  try {
    return await request<PartnerDetail>(`/partners/detail/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** Where this account stands with a company listing. */
export async function getClaim(id: string): Promise<ClaimStatus> {
  return request<ClaimStatus>(`/partners/claim/${id}`);
}

/** Begin proving that this account speaks for a company. */
export async function startClaim(id: string): Promise<ClaimStatus> {
  return request<ClaimStatus>(`/partners/claim/${id}`, { method: "POST" });
}

/** Fetch the proof from the company's own website. */
export async function verifyClaim(id: string): Promise<ClaimStatus> {
  return request<ClaimStatus>(`/partners/proof/${id}`, { method: "POST" });
}

/** Record that a person checked a reading and stands behind it. */
export async function setPartnerVerification(
  id: string,
  verified: boolean,
): Promise<Partner> {
  return request<Partner>(`/partners/verification/${id}`, {
    method: "POST",
    body: JSON.stringify({ verified }),
  });
}

/** Which companies can do this, by their own words. */
export async function matchPartners(
  requirement: string,
  limit = 8,
): Promise<CapabilityMatches> {
  return request<CapabilityMatches>("/partners/match", {
    method: "POST",
    body: JSON.stringify({ requirement, limit }),
  });
}

/** What buyers are asking for, published by them on purpose. */
export async function getRequests(options: {
  q?: string;
  method?: string;
  customerOwned?: boolean;
  limit?: number;
} = {}): Promise<DemandBoard> {
  const query = new URLSearchParams();
  if (options.q) query.set("q", options.q);
  if (options.method) query.set("method", options.method);
  if (options.customerOwned) query.set("customer_owned", "true");
  if (options.limit) query.set("limit", String(options.limit));
  const suffix = query.toString();
  return request<DemandBoard>(`/requests${suffix ? `?${suffix}` : ""}`);
}

/** What is live for one project, and what publishing would put on the board. */
export async function getPublication(projectId: string): Promise<Publication> {
  return request<Publication>(`/projects/${projectId}/publication`);
}

export async function publishRequest(
  projectId: string,
  body: { show_budget: boolean; note: string },
): Promise<Publication> {
  return request<Publication>(`/projects/${projectId}/publication`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function withdrawRequest(projectId: string): Promise<Publication> {
  return request<Publication>(`/projects/${projectId}/publication`, { method: "DELETE" });
}

/** German public contracts for printing, textiles and engraving. */
export async function getTenders(options: {
  q?: string;
  family?: string;
  berlin?: boolean;
  smes?: boolean;
  includeClosed?: boolean;
  limit?: number;
} = {}): Promise<TenderBoard> {
  const query = new URLSearchParams();
  if (options.q) query.set("q", options.q);
  if (options.family) query.set("family", options.family);
  if (options.berlin) query.set("berlin", "true");
  if (options.smes) query.set("smes", "true");
  if (options.includeClosed) query.set("include_closed", "true");
  if (options.limit) query.set("limit", String(options.limit));
  const suffix = query.toString();
  return request<TenderBoard>(`/tenders${suffix ? `?${suffix}` : ""}`);
}

/** One notice. */
export async function getTender(id: string): Promise<Tender | null> {
  try {
    return await request<Tender>(`/tenders/detail/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** Which companies in the directory say they can do this contract. */
export async function matchTender(id: string): Promise<CapabilityMatches> {
  return request<CapabilityMatches>(`/tenders/detail/${id}/matches`, { method: "POST" });
}

/** Everything the quote screen renders, in one read. */
export async function getQuoteDesk(id: string): Promise<QuoteDesk | null> {
  try {
    return await request<QuoteDesk>(`/projects/${id}/quotes`);
  } catch {
    // The desk is an extra on a finished project, so a failure here costs the
    // panel and never the page.
    return null;
  }
}

export async function captureQuote(id: string, replyText: string): Promise<QuoteDesk> {
  return request<QuoteDesk>(`/projects/${id}/quotes`, {
    method: "POST",
    body: JSON.stringify({ reply_text: replyText }),
  });
}

export async function confirmQuote(
  id: string,
  quoteId: string,
  corrections: Record<string, unknown>,
): Promise<QuoteDesk> {
  return request<QuoteDesk>(`/projects/${id}/quotes/${quoteId}/confirm`, {
    method: "POST",
    body: JSON.stringify(corrections),
  });
}

export async function deleteQuote(id: string, quoteId: string): Promise<QuoteDesk> {
  return request<QuoteDesk>(`/projects/${id}/quotes/${quoteId}`, { method: "DELETE" });
}

export async function getNearbyStudios(id: string): Promise<NearbyStudiosResponse> {
  return request<NearbyStudiosResponse>(`/projects/${encodeURIComponent(id)}/nearby-studios`);
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
