import type { MeshData, ProposeResponse } from "./types";

// REST calls to the FastAPI backend (proxied by Vite in dev).

export async function postPropose(intent: string, apiKey: string, model: string): Promise<ProposeResponse> {
  const res = await fetch("/propose", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ intent, api_key: apiKey || null, model: model || null }),
  });
  if (!res.ok) throw new Error(`propose failed: ${res.status}`);
  return res.json();
}

export async function fetchMesh(skin: number): Promise<MeshData> {
  const res = await fetch(`/mesh?skin=${encodeURIComponent(skin)}`);
  if (!res.ok) throw new Error(`mesh failed: ${res.status}`);
  return res.json();
}
