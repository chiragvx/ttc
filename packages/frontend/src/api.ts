import type { ChatEvent, MeshData } from "./types";
import type { LlmSettings } from "./settings";

// REST + SSE calls to the FastAPI backend (proxied by Vite in dev).

export async function fetchMesh(skin: number): Promise<MeshData> {
  const res = await fetch(`/mesh?skin=${encodeURIComponent(skin)}`);
  if (!res.ok) throw new Error(`mesh failed: ${res.status}`);
  return res.json();
}

// --- truth-plane analysis loop ---
export async function analyze(loadN = 40): Promise<any> {
  return (await fetch(`/analyze?load_n=${loadN}`, { method: "POST" })).json();
}
export async function analyzeStatus(): Promise<any> {
  return (await fetch("/analyze/status")).json();
}
export async function optimize(loadN = 25): Promise<any> {
  return (await fetch(`/optimize?load_n=${loadN}`, { method: "POST" })).json();
}
export async function optimizeStatus(): Promise<any> {
  return (await fetch("/optimize/status")).json();
}
export async function exportCheck(): Promise<{ status: string; reasons: string[]; unknowns: string[] }> {
  return (await fetch("/export/check", { method: "POST" })).json();
}

// --- goal-grounded requirements (the design agent's targets, judged vs live metrics) ---
export interface RequirementRow {
  id: string; text: string; metric: string; op: string; target: number;
  method: string; status: "SATISFIED" | "VIOLATED" | "UNKNOWN"; value: number | null;
}
export interface RequirementsData {
  goal_set: boolean; implied_fs_floor: number | null;
  satisfied: number; total: number; requirements: RequirementRow[];
  metrics: Record<string, number | null>;
}
export async function setGoal(goal: string): Promise<RequirementsData> {
  return (await fetch("/requirements", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goal }),
  })).json();
}
export async function getRequirements(): Promise<RequirementsData> {
  return (await fetch("/requirements")).json();
}
export async function signoff(): Promise<void> {
  await fetch("/signoff?reviewer=engineer", { method: "POST" });
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
