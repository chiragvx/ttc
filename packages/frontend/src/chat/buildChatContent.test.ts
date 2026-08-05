import { describe, expect, it } from "vitest";

import { buildChatContent } from "./buildChatContent";

describe("buildChatContent", () => {
  it("returns the plain text string unchanged when there is no image", () => {
    expect(buildChatContent("hello", null, true)).toBe("hello");
  });

  it("returns the plain text string unchanged when there is an image but the model isn't vision-capable", () => {
    expect(buildChatContent("hello", "data:image/png;base64,AAAA", false)).toBe("hello");
  });

  it("returns the plain text string unchanged when the image data URL is an empty string", () => {
    // empty string is falsy -- treated the same as null (no image)
    expect(buildChatContent("hello", "", true)).toBe("hello");
  });

  it("returns a multimodal content array only when both an image AND vision capability are present", () => {
    const result = buildChatContent("hello", "data:image/png;base64,AAAA", true);
    expect(Array.isArray(result)).toBe(true);
    const parts = result as Array<{ type: string; text?: string; image_url?: { url: string } }>;
    expect(parts).toHaveLength(2);
    expect(parts[0].type).toBe("text");
    expect(parts[0].text).toBe("hello");
    expect(parts[0].image_url).toBeUndefined();
    expect(parts[1].type).toBe("image_url");
    expect(parts[1].text).toBeUndefined();
    expect(parts[1].image_url).toEqual({ url: "data:image/png;base64,AAAA" });
  });
});
