/**
 * Tests for the one place the client contains real logic: translating the API's
 * error envelope into something a screen can show.
 *
 * There is deliberately nothing here about scoring, stage order or field
 * requirements - none of that lives in the frontend, so testing it here would be
 * testing a duplicate of the server's rules.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, getHealth, listProjects, resumeProject } from "../lib/api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("error translation", () => {
  it("surfaces the backend's own message and code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            error: {
              code: "http_409",
              message: "This project is not waiting for 'approve_rfq'.",
              stage: "brief_review",
              recoverable: true,
            },
          },
          409,
        ),
      ),
    );

    await expect(resumeProject("p1", "approve_rfq")).rejects.toMatchObject({
      status: 409,
      code: "http_409",
      recoverable: true,
      message: "This project is not waiting for 'approve_rfq'.",
    });
  });

  it("explains an unreachable API instead of leaking 'fetch failed'", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));

    const failure = await listProjects().catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).code).toBe("api_unreachable");
    expect((failure as ApiError).message).toContain("Start the backend");
  });

  it("treats a 5xx as unrecoverable when the body says nothing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("not json", { status: 500 })),
    );

    const failure = (await listProjects().catch((error: unknown) => error)) as ApiError;

    expect(failure.status).toBe(500);
    expect(failure.recoverable).toBe(false);
  });

  it("lets the dashboard render when health is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));

    // A missing status banner is better than a blank dashboard, so this one
    // swallows the failure rather than propagating it.
    await expect(getHealth()).resolves.toBeNull();
  });
});

describe("request shape", () => {
  it("sends the action and its data in one body", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ project_id: "p1", stage: "rfq_review" }));
    vi.stubGlobal("fetch", fetchMock);

    await resumeProject("p1", "select_supplier", { supplier_id: "syn-004" });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/projects/p1/resume");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      action: "select_supplier",
      supplier_id: "syn-004",
    });
  });

  it("percent-encodes the project id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ projects: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await resumeProject("a/../b", "confirm_brief");

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("a%2F..%2Fb");
    expect(url).not.toContain("a/../b");
  });
});
