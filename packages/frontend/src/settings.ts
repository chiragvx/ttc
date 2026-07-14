export interface LlmSettings {
  apiKey: string;
  model: string;
  // The server-side AUTH_TOKEN (2026-07-15), if the operator configured one — sent as
  // `Authorization: Bearer <authToken>` on every REST call (see api.ts::apiFetch). Empty/unset is
  // fine and matches this app's default (open, unauthenticated) behavior; only meaningful once the
  // backend is deployed with AUTH_TOKEN set.
  authToken: string;
}

const KEY = "openrouter_key";
const MODEL = "openrouter_model";
const AUTH_TOKEN = "gtc_auth_token";
export const DEFAULT_MODEL = "deepseek/deepseek-chat";

export function loadSettings(): LlmSettings {
  return {
    apiKey: localStorage.getItem(KEY) ?? "",
    model: localStorage.getItem(MODEL) ?? DEFAULT_MODEL,
    authToken: localStorage.getItem(AUTH_TOKEN) ?? "",
  };
}

export function saveSettings(s: LlmSettings): void {
  localStorage.setItem(KEY, s.apiKey);
  localStorage.setItem(MODEL, s.model || DEFAULT_MODEL);
  localStorage.setItem(AUTH_TOKEN, s.authToken);
}

export function clearKey(): void {
  localStorage.removeItem(KEY);
}
