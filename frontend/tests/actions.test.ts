/**
 * The bug this file exists to pin: a stage-mismatch response (409) is the
 * backend's documented way of telling a stale tab "the project already moved
 * on, here is what it actually expects now" - but `advance()` was returning
 * the raw error and skipping `revalidatePath`, so the page never refetched
 * the real state. A user answering a question the project had already moved
 * past saw a jargon-filled error ("not waiting for 'answer_clarification'.
 * It expects 'confirm_brief'.") and stayed stuck on the same dead form
 * forever - the one case the 409 design exists to recover from was the one
 * case that never recovered.
 *
 * Every stage transition (clarification, brief, method, supplier, RFQ) goes
 * through this one function, so it is tested once here rather than once per
 * screen.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

const revalidatePath = vi.fn();
vi.mock("next/cache", () => ({ revalidatePath }));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));

const resumeProject = vi.fn();
vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return { ...actual, resumeProject };
});

const { ApiError } = await import("../lib/api");
const { answerClarification, confirmBrief } = await import("../lib/actions");

function formWith(answer: string): FormData {
  const data = new FormData();
  data.set("answer", answer);
  return data;
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("a stage mismatch (409)", () => {
  it("revalidates instead of leaving the stale form on screen", async () => {
    resumeProject.mockRejectedValue(
      new ApiError(
        "This project is not waiting for 'answer_clarification'. It expects 'confirm_brief'.",
        409,
        "http_409",
      ),
    );

    const result = await answerClarification("p1", undefined, formWith("cotton"));

    // No error surfaced: the recovery is a fresh render of the real step, not
    // a message about a step the user cannot act on any more.
    expect(result).toEqual({});
    expect(revalidatePath).toHaveBeenCalledWith("/projects/p1");
  });

  it("does the same for every other stage action, not only clarification", async () => {
    resumeProject.mockRejectedValue(
      new ApiError("This project is not waiting for 'confirm_brief'. It expects 'confirm_method'.", 409, "http_409"),
    );

    const result = await confirmBrief("p1");

    expect(result).toEqual({});
    expect(revalidatePath).toHaveBeenCalledWith("/projects/p1");
  });
});

describe("an ordinary failure", () => {
  it("is still shown, and still does not revalidate", async () => {
    resumeProject.mockRejectedValue(new ApiError("The server is unavailable.", 503, "http_503"));

    const result = await answerClarification("p1", undefined, formWith("cotton"));

    expect(result).toEqual({ error: "The server is unavailable." });
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("falls back to a generic message for a non-API error", async () => {
    resumeProject.mockRejectedValue(new TypeError("network down"));

    const result = await answerClarification("p1", undefined, formWith("cotton"));

    expect(result).toEqual({ error: "Something went wrong." });
  });
});

describe("success", () => {
  it("revalidates both the project and the dashboard", async () => {
    resumeProject.mockResolvedValue(undefined);

    const result = await answerClarification("p1", undefined, formWith("cotton"));

    expect(result).toEqual({});
    expect(revalidatePath).toHaveBeenCalledWith("/projects/p1");
    expect(revalidatePath).toHaveBeenCalledWith("/dashboard");
  });
});
