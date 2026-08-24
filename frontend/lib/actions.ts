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
  createProject,
  generateDesign,
  getNearbyStudios,
  resumeProject,
  uploadDesign,
} from "./api";
import type { GeneratedDesign, NearbyStudio, ResumeAction, UploadResponse } from "./types";

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

  revalidatePath("/");
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
  revalidatePath("/");
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
