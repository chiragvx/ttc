export interface LlmSettings {
  apiKey: string;
  model: string;
  // The server-side AUTH_TOKEN (2026-07-15), if the operator configured one — sent as
  // `Authorization: Bearer <authToken>` on every REST call (see api.ts::apiFetch). Empty/unset is
  // fine and matches this app's default (open, unauthenticated) behavior; only meaningful once the
  // backend is deployed with AUTH_TOKEN set.
  authToken: string;
  // A vision-capable OpenRouter model id for the visual self-check (packages/agents/vision_validator.py)
  // (2026-07-22). Reuses the SAME `apiKey` above — OpenRouter is one account across models, so no
  // separate key is needed. Empty/unset means visual validation stays off, matching the backend's own
  // "gated and OFF by default" posture (packages/transport/app.py's ValidateRequest.vision_model
  // already accepts a per-request override; this is purely the frontend surfacing of that).
  visionModel: string;
}

const KEY = "openrouter_key";
const MODEL = "openrouter_model";
const AUTH_TOKEN = "gtc_auth_token";
const VISION_MODEL = "vision_model";
export const DEFAULT_MODEL = "deepseek/deepseek-chat";

export function loadSettings(): LlmSettings {
  return {
    apiKey: localStorage.getItem(KEY) ?? "",
    model: localStorage.getItem(MODEL) ?? DEFAULT_MODEL,
    authToken: localStorage.getItem(AUTH_TOKEN) ?? "",
    visionModel: localStorage.getItem(VISION_MODEL) ?? "",
  };
}

export function saveSettings(s: LlmSettings): void {
  localStorage.setItem(KEY, s.apiKey);
  localStorage.setItem(MODEL, s.model || DEFAULT_MODEL);
  localStorage.setItem(AUTH_TOKEN, s.authToken);
  localStorage.setItem(VISION_MODEL, s.visionModel);
}

export function clearKey(): void {
  localStorage.removeItem(KEY);
}
