export interface LlmSettings {
  apiKey: string;
  model: string;
}

const KEY = "openrouter_key";
const MODEL = "openrouter_model";
export const DEFAULT_MODEL = "deepseek/deepseek-chat";

export function loadSettings(): LlmSettings {
  return {
    apiKey: localStorage.getItem(KEY) ?? "",
    model: localStorage.getItem(MODEL) ?? DEFAULT_MODEL,
  };
}

export function saveSettings(s: LlmSettings): void {
  localStorage.setItem(KEY, s.apiKey);
  localStorage.setItem(MODEL, s.model || DEFAULT_MODEL);
}

export function clearKey(): void {
  localStorage.removeItem(KEY);
}
