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

import { ApiError, createProject, resumeProject } from "./api";
import type { ResumeAction } from "./types";

export interface ActionResult {
  error?: string;
}

export async function startProject(
  _previous: ActionResult | undefined,
  formData: FormData,
): Promise<ActionResult> {
  const text = String(formData.get("request_text") ?? "").trim();

  if (text.length < 10) {
    return { error: "Please describe the job in a little more detail." };
  }

  let projectId: string;
  try {
    const state = await createProject(text);
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
