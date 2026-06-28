import type { ChatEvent, MeshData } from "./types";
import type { LlmSettings } from "./settings";

// REST + SSE calls to the FastAPI backend (proxied by Vite in dev).

export async function fetchMesh(skin: number): Promise<MeshData> {
  const res = await fetch(`/mesh?skin=${encodeURIComponent(skin)}`);
  if (!res.ok) throw new Error(`mesh failed: ${res.status}`);
  return res.json();
}

// Stream a conversational reply. Calls onEvent for each SSE event; abortable via signal.
export async function streamChat(
  messages: Array<{ role: string; content: string }>,
  settings: LlmSettings,
  onEvent: (e: ChatEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, api_key: settings.apiKey || null, model: settings.model || null }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`chat failed: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const frames = buf.split("\n\n");
    buf = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(6)) as ChatEvent);
      } catch {
        /* ignore malformed frame */
      }
    }
  }
}
