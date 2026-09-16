"use server";

/**
 * Server actions - every mutation the UI can perform.
 *
 * Each one is a thin pass-through to the API. There is deliberately no logic
 * here about which action is valid at which stage: the backend rejects a
 * mismatched action with a 409 naming what it actually expects, and duplicating
 * that rule in the client would create a second source of truth that could
 * drift.
 */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import {
  ApiError,
  captureQuote,
  claimProject,
  confirmQuote,
  createProject,
  deleteQuote,
  generateDesign,
  getClaim,
  getNearbyStudios,
  getPublication,
  matchPartners,
  matchTender,
  publishRequest,
  resumeProject,
  setPartnerVerification,
  startClaim,
  verifyClaim,
  withdrawRequest,
  submitFeedback,
  uploadDesign,
} from "./api";
import type {
  CapabilityMatches,
  ClaimStatus,
  Publication,
  FeedbackRequest,
  GeneratedDesign,
  NearbyStudio,
  QuoteDesk,
  ResumeAction,
  UploadResponse,
} from "./types";

export interface ActionResult {
  error?: string;
}

export async function startProject(
  _previous: ActionResult | undefined,
  formData: FormData,
): Promise<ActionResult> {
  const text = String(formData.get("request_text") ?? "").trim();
  const designUploadId = String(formData.get("design_upload_id") ?? "").trim();

  if (text.length < 10) {
    return { error: "Please describe the job in a little more detail." };
  }

  let projectId: string;
  try {
    const state = await createProject(text, designUploadId || undefined);
    projectId = state.project_id;
  } catch (error) {
    return {
      error:
        error instanceof ApiError
          ? error.message
          : "Something went wrong starting the project.",
    };
  }

  revalidatePath("/dashboard");
  redirect(`/projects/${projectId}`);
}

export interface DesignActionResult {
  error?: string;
  upload?: UploadResponse;
  /** Only present for a generated design - see {@link GeneratedDesign}. */
  previewDataUrl?: string;
}

export async function uploadDesignAction(formData: FormData): Promise<DesignActionResult> {
  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0) {
    return { error: "Please choose a file." };
  }

  try {
    const upload = await uploadDesign(file);
    return { upload };
  } catch (error) {
    return {
      error: error instanceof ApiError ? error.message : "The upload failed.",
    };
  }
}

export async function generateDesignAction(prompt: string): Promise<DesignActionResult> {
  const trimmed = prompt.trim();
  if (trimmed.length < 3) {
    return { error: "Describe the design in a few more words." };
  }

  try {
    const generated: GeneratedDesign = await generateDesign(trimmed);
    return { upload: generated, previewDataUrl: generated.preview_data_url };
  } catch (error) {
    return {
      error: error instanceof ApiError ? error.message : "Generation failed.",
    };
  }
}

export interface NearbyStudiosResult {
  error?: string;
  studios?: NearbyStudio[];
  note?: string;
}

/**
 * Fetched on demand from a client component (the "show nearby studios"
 * toggle on the partner-matches screen), not on page load - Overpass is a
 * shared public service and a project's method rarely changes once
 * confirmed, so there is no reason to query it every time the page renders.
 */
export async function loadNearbyStudios(projectId: string): Promise<NearbyStudiosResult> {
  try {
    const response = await getNearbyStudios(projectId);
    return { studios: response.studios, note: response.note };
  } catch (error) {
    return {
      error: error instanceof ApiError ? error.message : "Could not reach OpenStreetMap.",
    };
  }
}

export async function submitFeedbackAction(
  projectId: string,
  feedback: FeedbackRequest,
): Promise<ActionResult> {
  try {
    await submitFeedback(projectId, feedback);
  } catch (error) {
    return {
      error: error instanceof ApiError ? error.message : "Could not record your answer.",
    };
  }
  return {};
}

/**
 * Take ownership of a project that has none.
 *
 * The one place an account changes what you can see rather than merely who you
 * are. A project that already has an owner answers 404 here, same as any other
 * project you cannot see - so this cannot be used to find out whether one
 * exists.
 */
export async function claimProjectAction(projectId: string): Promise<ActionResult> {
  try {
    await claimProject(projectId);
  } catch (error) {
    return {
      error:
        error instanceof ApiError ? error.message : "Could not keep this project.",
    };
  }
  revalidatePath(`/projects/${projectId}`);
  revalidatePath("/dashboard");
  return {};
}

export interface QuoteDeskResult {
  desk?: QuoteDesk;
  error?: string;
}

/**
 * Read one pasted supplier reply.
 *
 * Returns the whole desk rather than the one quote: capturing a reply changes
 * the comparison and the follow-ups too, and re-deriving those in the browser
 * would be a second implementation of rules that live on the server.
 */
export async function captureQuoteAction(
  projectId: string,
  replyText: string,
): Promise<QuoteDeskResult> {
  try {
    return { desk: await captureQuote(projectId, replyText) };
  } catch (error) {
    return {
      error: error instanceof ApiError ? error.message : "Could not read that reply.",
    };
  }
}

export async function confirmQuoteAction(
  projectId: string,
  quoteId: string,
  corrections: Record<string, unknown>,
): Promise<QuoteDeskResult> {
  try {
    return { desk: await confirmQuote(projectId, quoteId, corrections) };
  } catch (error) {
    return {
      error: error instanceof ApiError ? error.message : "Could not save your correction.",
    };
  }
}

export async function deleteQuoteAction(
  projectId: string,
  quoteId: string,
): Promise<QuoteDeskResult> {
  try {
    return { desk: await deleteQuote(projectId, quoteId) };
  } catch (error) {
    return {
      error: error instanceof ApiError ? error.message : "Could not remove that reply.",
    };
  }
}

async function advance(
  projectId: string,
  action: ResumeAction,
  data: Record<string, unknown> = {},
): Promise<ActionResult> {
  try {
    await resumeProject(projectId, action, data);
  } catch (error) {
    return {
      error:
        error instanceof ApiError ? error.message : "Something went wrong.",
    };
  }
  revalidatePath(`/projects/${projectId}`);
  revalidatePath("/dashboard");
  return {};
}

export async function answerClarification(
  projectId: string,
  _previous: ActionResult | undefined,
  formData: FormData,
): Promise<ActionResult> {
  const answer = String(formData.get("answer") ?? "").trim();
  if (!answer) {
    return { error: "Please answer the question to continue." };
  }
  return advance(projectId, "answer_clarification", { answer });
}

export async function restartRequest(
  projectId: string,
  _previous: ActionResult | undefined,
  formData: FormData,
): Promise<ActionResult> {
  const rawRequest = String(formData.get("raw_request") ?? "").trim();
  if (rawRequest.length < 10) {
    return { error: "Please describe the job in a little more detail." };
  }
  return advance(projectId, "restart_request", { raw_request: rawRequest });
}

export async function confirmBrief(projectId: string): Promise<ActionResult> {
  return advance(projectId, "confirm_brief");
}

export async function editBrief(
  projectId: string,
  requirement: Record<string, unknown>,
): Promise<ActionResult> {
  return advance(projectId, "edit_brief", { requirement });
}

export async function confirmMethod(
  projectId: string,
  method: string,
): Promise<ActionResult> {
  return advance(projectId, "confirm_method", { method });
}

export async function selectSupplier(
  projectId: string,
  supplierId: string,
): Promise<ActionResult> {
  return advance(projectId, "select_supplier", { supplier_id: supplierId });
}

export async function approveRfq(projectId: string): Promise<ActionResult> {
  return advance(projectId, "approve_rfq", { approved: true });
}

export async function editRfq(
  projectId: string,
  rfq: Record<string, unknown>,
): Promise<ActionResult> {
  return advance(projectId, "edit_rfq", { rfq, approved: true });
}

export interface VerificationResult extends ActionResult {
  verified?: boolean;
}

/**
 * Record that a person checked what was read from a company's site.
 *
 * The one fact in the directory no amount of scraping can produce. A model read
 * the page and a verifier checked that every quote is really on it; neither of
 * those is somebody saying "yes, this is what they do".
 */
export async function setVerificationAction(
  partnerId: string,
  verified: boolean,
): Promise<VerificationResult> {
  try {
    const partner = await setPartnerVerification(partnerId, verified);
    revalidatePath("/companies");
    revalidatePath(`/companies/${partnerId}`);
    return { verified: partner.verified };
  } catch (error) {
    return {
      error:
        error instanceof ApiError
          ? error.message
          : "The confirmation could not be saved.",
    };
  }
}

export interface MatchResult extends ActionResult {
  matches?: CapabilityMatches;
}

/**
 * Search the companies by what they said they can do.
 *
 * A failure costs the panel and never the page: the directory and the
 * deterministic matcher both work without retrieval, and a search that cannot
 * run is not a reason to show somebody an error screen instead of 135
 * companies.
 */
export async function matchPartnersAction(requirement: string): Promise<MatchResult> {
  const trimmed = requirement.trim();
  if (trimmed.length < 3) {
    return { error: "Describe what you need in a few more words." };
  }
  try {
    return { matches: await matchPartners(trimmed) };
  } catch (error) {
    return {
      error:
        error instanceof ApiError
          ? error.message
          : "The search could not be run just now.",
    };
  }
}

/**
 * Which companies say they can do one public contract.
 *
 * A failure costs the panel and never the page: a tender is worth reading
 * whether or not this product can tell you who might bid for it.
 */
export async function matchTenderAction(tenderId: string): Promise<MatchResult> {
  try {
    return { matches: await matchTender(tenderId) };
  } catch (error) {
    return {
      error:
        error instanceof ApiError ? error.message : "The search could not be run just now.",
    };
  }
}

export interface PublicationResult extends ActionResult {
  publication?: Publication;
}

/**
 * Put a project's request on the public board, or take it down.
 *
 * Always the buyer's explicit act, and always reversible. Nothing publishes
 * itself: a brief written for this product is not a brief written for
 * strangers, and the difference is theirs to decide rather than a default to
 * discover afterwards.
 */
export async function publishRequestAction(
  projectId: string,
  body: { show_budget: boolean; note: string },
): Promise<PublicationResult> {
  try {
    const publication = await publishRequest(projectId, body);
    revalidatePath("/requests");
    revalidatePath(`/projects/${projectId}`);
    return { publication };
  } catch (error) {
    return {
      error: error instanceof ApiError ? error.message : "The listing could not be published.",
    };
  }
}

export async function withdrawRequestAction(projectId: string): Promise<PublicationResult> {
  try {
    const publication = await withdrawRequest(projectId);
    revalidatePath("/requests");
    revalidatePath(`/projects/${projectId}`);
    return { publication };
  } catch (error) {
    return {
      error: error instanceof ApiError ? error.message : "The listing could not be taken down.",
    };
  }
}

/** The buyer's current publication state, for the panel's first render. */
export async function loadPublicationAction(projectId: string): Promise<PublicationResult> {
  try {
    return { publication: await getPublication(projectId) };
  } catch {
    return { error: "The publication panel could not be loaded." };
  }
}

export interface ClaimResult extends ActionResult {
  claim?: ClaimStatus;
}

/**
 * Claiming a company listing, in three server actions.
 *
 * The token never passes through a URL or a client-side store: it comes back
 * from the server only to the account holding the claim, is shown once on the
 * page, and is checked by the server fetching the company's own website.
 */
export async function loadClaimAction(partnerId: string): Promise<ClaimResult> {
  try {
    return { claim: await getClaim(partnerId) };
  } catch (error) {
    // 401 is the ordinary case for a signed-out visitor, not a failure: the
    // panel simply does not appear for them.
    if (error instanceof ApiError && error.status === 401) return {};
    return { error: "The claim panel could not be loaded." };
  }
}

export async function startClaimAction(partnerId: string): Promise<ClaimResult> {
  try {
    return { claim: await startClaim(partnerId) };
  } catch (error) {
    return {
      error: error instanceof ApiError ? error.message : "The claim could not be started.",
    };
  }
}

export async function verifyClaimAction(partnerId: string): Promise<ClaimResult> {
  try {
    const claim = await verifyClaim(partnerId);
    revalidatePath(`/companies/${partnerId}`);
    return { claim };
  } catch (error) {
    return {
      error: error instanceof ApiError ? error.message : "The proof could not be checked.",
    };
  }
}
