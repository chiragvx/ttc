import type { ChatContentPart } from "../types";

// Builds the outgoing `content` for a chat turn — plain text (the overwhelming common case, and the
// ONLY case for every turn except an auto-correction one) or, when a rendered blueprint image is
// available AND the configured model can actually see it, a multimodal content array carrying both
// (2026-08-05). Pure/testable, matching this codebase's established "extract the risky pure logic"
// pattern (summarizeOutcomes.ts, exportConversation.ts).
//
// The array shape mirrors packages/agents/openrouter_provider.py::judge_image's own image-message
// JSON exactly (field names `type`/`text`/`image_url`/`url`) — the backend does zero inspection of
// `content`'s shape, it's pure pass-through to OpenRouter, so matching judge_image's proven-working
// shape here is what makes this work with zero backend changes.
export function buildChatContent(
  text: string,
  imageDataUrl: string | null,
  visionCapable: boolean,
): string | ChatContentPart[] {
  if (!imageDataUrl || !visionCapable) return text;
  return [
    { type: "text", text },
    { type: "image_url", image_url: { url: imageDataUrl } },
  ];
}
