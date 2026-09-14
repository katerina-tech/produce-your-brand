import { describe, expect, it } from "vitest";

import { fitsInAUrl, gmailUrl, looksLikeAnAddress, mailtoUrl } from "../lib/outreach";

const DRAFT = {
  to: "hallo@example.de",
  subject: "Quotation request: 100 t-shirts",
  body: "We are sourcing a print run.\n\n- Quantity: 100\n\nThank you.",
};

describe("gmailUrl", () => {
  it("opens the compose view and nothing else", () => {
    const url = new URL(gmailUrl(DRAFT));

    expect(url.host).toBe("mail.google.com");
    expect(url.searchParams.get("view")).toBe("cm");
    // The absence worth asserting: no parameter here sends. A person does.
    expect(url.searchParams.get("send")).toBeNull();
  });

  it("carries the message intact, newlines included", () => {
    const url = new URL(gmailUrl(DRAFT));

    expect(url.searchParams.get("to")).toBe(DRAFT.to);
    expect(url.searchParams.get("su")).toBe(DRAFT.subject);
    expect(url.searchParams.get("body")).toBe(DRAFT.body);
  });

  it("survives an address we do not have", () => {
    const url = new URL(gmailUrl({ ...DRAFT, to: "" }));

    expect(url.searchParams.get("to")).toBe("");
    expect(url.searchParams.get("body")).toBe(DRAFT.body);
  });

  it("encodes a subject that would otherwise break the query", () => {
    const url = new URL(gmailUrl({ ...DRAFT, subject: "100 shirts & caps = ?" }));

    expect(url.searchParams.get("subject")).toBeNull();
    expect(url.searchParams.get("su")).toBe("100 shirts & caps = ?");
  });
});

describe("mailtoUrl", () => {
  it("addresses the message and keeps the body", () => {
    const url = mailtoUrl(DRAFT);

    expect(url.startsWith("mailto:hallo%40example.de?")).toBe(true);
    expect(url).toContain("subject=Quotation");
    // A body arriving as one run-on paragraph is the classic silent failure.
    expect(url).toContain("%0A");
  });
});

describe("fitsInAUrl", () => {
  it("accepts an ordinary enquiry", () => {
    expect(fitsInAUrl(DRAFT)).toBe(true);
  });

  it("refuses one a link would truncate", () => {
    expect(fitsInAUrl({ ...DRAFT, body: "a very long note ".repeat(600) })).toBe(false);
  });
});

describe("looksLikeAnAddress", () => {
  it("accepts what people actually type", () => {
    expect(looksLikeAnAddress("hallo@example.de")).toBe(true);
    expect(looksLikeAnAddress("  info@sieb-druck.berlin  ")).toBe(true);
    expect(looksLikeAnAddress("a.b+tag@sub.domain.co.uk")).toBe(true);
  });

  it("rejects what cannot be an address", () => {
    expect(looksLikeAnAddress("")).toBe(false);
    expect(looksLikeAnAddress("not-an-address")).toBe(false);
    expect(looksLikeAnAddress("@example.de")).toBe(false);
    expect(looksLikeAnAddress("hallo@")).toBe(false);
    expect(looksLikeAnAddress("hallo@localhost")).toBe(false);
    expect(looksLikeAnAddress("two@at@signs.de")).toBe(false);
    expect(looksLikeAnAddress("has space@example.de")).toBe(false);
  });
});
