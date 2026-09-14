import { describe, expect, it } from "vitest";

import { appendDictation, preferredLanguage } from "../lib/dictation";

/**
 * Speech recognition hands back fragments with no leading space and no
 * knowledge of what came before, so the joining is ours to get wrong. Each
 * case here is a way it looked wrong before the rule existed.
 */
describe("appendDictation", () => {
  it("starts an empty box at the beginning, not at a space", () => {
    expect(appendDictation("", "I have 100 tote bags")).toBe("I have 100 tote bags");
  });

  it("separates a new phrase from the last word", () => {
    expect(appendDictation("I have 100 tote bags", "delivered to Potsdam")).toBe(
      "I have 100 tote bags delivered to Potsdam",
    );
  });

  it("does not double a space somebody already typed", () => {
    expect(appendDictation("I have 100 tote bags ", "delivered to Potsdam")).toBe(
      "I have 100 tote bags delivered to Potsdam",
    );
  });

  it("glues punctuation to the word rather than floating it", () => {
    expect(appendDictation("delivered to Potsdam", ".")).toBe("delivered to Potsdam.");
    expect(appendDictation("100 mats ", ",")).toBe("100 mats,");
  });

  it("ignores a fragment that is only whitespace", () => {
    expect(appendDictation("I have 100 tote bags", "   ")).toBe("I have 100 tote bags");
  });

  it("trims the recogniser's own padding", () => {
    expect(appendDictation("gold logo", "  in Berlin  ")).toBe("gold logo in Berlin");
  });

  it("keeps a typed line break instead of flattening it", () => {
    expect(appendDictation("First line\n", "second line")).toBe("First line\nsecond line");
  });
});

describe("preferredLanguage", () => {
  it("starts a German browser in German", () => {
    expect(preferredLanguage("de-DE")).toBe("de-DE");
    expect(preferredLanguage("de")).toBe("de-DE");
    expect(preferredLanguage("DE-de")).toBe("de-DE");
  });

  it("falls back to English for anything else, including nothing at all", () => {
    expect(preferredLanguage("en-GB")).toBe("en-US");
    expect(preferredLanguage("ru-RU")).toBe("en-US");
    expect(preferredLanguage(undefined)).toBe("en-US");
  });
});
