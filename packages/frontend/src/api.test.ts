import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { analyze, analyzeStatus, fetchBlueprintDataUrl, fetchDesignReport, fetchModelVisionCapable, optimize, runValidate, signoff } from "./api";

// Captures exactly what apiFetch handed to the real fetch() — this is what pins down the
// 2026-07-15 load-threading fix: analyze()/analyzeStatus()/optimize() must OMIT load_n by default
// (so the backend's own goal-resolution, packages/transport/app.py::effective_load_n, applies) and
// only append it when the caller explicitly overrides. Before that fix, App.tsx always passed a
// hardcoded 40/25, silently overriding whatever the stated goal demanded.
function stubFetch() {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
  }));
  return calls;
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("analyze/analyzeStatus/optimize load_n resolution", () => {
  it("omits load_n by default, letting the backend resolve it from the goal", async () => {
    const calls = stubFetch();
    await analyze();
    await analyzeStatus();
    await optimize();
    expect(calls.map((c) => c.url)).toEqual(["/analyze", "/analyze/status", "/optimize"]);
  });

  it("appends load_n only when explicitly passed", async () => {
    const calls = stubFetch();
    await analyze(200);
    await analyzeStatus(200);
    await optimize(150);
    expect(calls.map((c) => c.url)).toEqual([
      "/analyze?load_n=200", "/analyze/status?load_n=200", "/optimize?load_n=150",
    ]);
  });

  it("posts to /analyze and /optimize but only GETs /analyze/status", async () => {
    const calls = stubFetch();
    await analyze();
    await analyzeStatus();
    await optimize();
    expect(calls[0].init?.method).toBe("POST");
    expect(calls[1].init?.method).toBeUndefined(); // GET (no method specified)
    expect(calls[2].init?.method).toBe("POST");
  });
});

// 2026-08-04 -- GET /report returns plain text/markdown (mirroring /blueprint's PNG), not JSON --
// fetchDesignReport must call .text(), not .json(), and surface a non-ok response as a real error
// instead of silently returning something empty/garbled.
describe("fetchDesignReport", () => {
  it("GETs /report and returns the raw markdown text", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response("# Design report\n\nNo parts in this file yet.\n", { status: 200 })));
    const md = await fetchDesignReport();
    expect(md).toContain("# Design report");
    expect(md).toContain("No parts in this file yet.");
  });

  it("throws when the backend responds with a non-ok status", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 500 })));
    await expect(fetchDesignReport()).rejects.toThrow("report failed: 500");
  });
});

describe("apiFetch auth header (settings.ts::loadSettings -> Authorization)", () => {
  it("sends no Authorization header when no auth token is configured", async () => {
    const calls = stubFetch();
    await analyze();
    expect((calls[0].init?.headers as Record<string, string> | undefined)?.Authorization).toBeUndefined();
  });

  it("sends Authorization: Bearer <token> once an auth token is configured", async () => {
    localStorage.setItem("gtc_auth_token", "secret123");
    const calls = stubFetch();
    await analyze();
    expect((calls[0].init?.headers as Record<string, string>).Authorization).toBe("Bearer secret123");
  });
});

// 2026-07-22 -- the Settings-modal vision-model field (settings.ts::LlmSettings.visionModel) has to
// actually reach the backend's per-request ValidateRequest.vision_model override
// (packages/transport/app.py) for the visual self-check to ever turn on client-side.
describe("runValidate vision_model threading", () => {
  it("sends vision_model: null when no vision model is configured", async () => {
    const calls = stubFetch();
    await runValidate("intent", "key123");
    expect(JSON.parse(calls[0].init!.body as string)).toEqual({
      intent: "intent", api_key: "key123", vision_model: null,
    });
  });

  it("sends the configured vision model straight through", async () => {
    const calls = stubFetch();
    await runValidate("intent", "key123", "a-vision-capable-model");
    expect(JSON.parse(calls[0].init!.body as string)).toEqual({
      intent: "intent", api_key: "key123", vision_model: "a-vision-capable-model",
    });
  });
});

// 2026-08-05 -- fetchModelVisionCapable/fetchBlueprintDataUrl back the vision-in-the-loop feature
// (chat/buildChatContent.ts): whether the configured model can see, and the self-check's rendered
// blueprint as a data: URL to hand it.
describe("fetchModelVisionCapable", () => {
  it("returns the real boolean from a successful response", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({ vision: true }), { status: 200 })));
    await expect(fetchModelVisionCapable("openai/gpt-5.6-luna")).resolves.toBe(true);
  });

  it("returns false from a successful response reporting no vision support", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({ vision: false }), { status: 200 })));
    await expect(fetchModelVisionCapable("deepseek/deepseek-v4-flash")).resolves.toBe(false);
  });

  it("hits /model_capabilities with the model name query-encoded", async () => {
    const calls = stubFetch();
    await fetchModelVisionCapable("openai/gpt-5.6-luna");
    expect(calls[0].url).toBe("/model_capabilities?model=openai%2Fgpt-5.6-luna");
  });

  it("returns false (never throws) on a non-ok response", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 500 })));
    await expect(fetchModelVisionCapable("any-model")).resolves.toBe(false);
  });

  it("returns false (never throws) on a network error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("network down"); }));
    await expect(fetchModelVisionCapable("any-model")).resolves.toBe(false);
  });
});

describe("fetchBlueprintDataUrl", () => {
  it("converts a stubbed Blob response into a data: URL string", async () => {
    const blob = new Blob(["fake-png-bytes"], { type: "image/png" });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(blob, { status: 200 })));
    const dataUrl = await fetchBlueprintDataUrl();
    expect(dataUrl).toMatch(/^data:/);
  });

  it("throws on a non-ok status", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 500 })));
    await expect(fetchBlueprintDataUrl()).rejects.toThrow("blueprint failed: 500");
  });
});

// 2026-07-19 -- /signoff now 409s on a design that hasn't been analyzed at its current geometry
// (packages/transport/app.py::signoff). signoff() used to return bare Promise<void>, silently
// resolving even when the backend refused to flip review.state; it must now surface the block.
describe("signoff", () => {
  it("resolves { ok: true } on a normal 200 response", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 })));
    await expect(signoff()).resolves.toEqual({ ok: true });
  });

  it("resolves { ok: false, message, unknowns } on a 409 instead of throwing", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ status: "error", message: "cannot sign off: ...", unknowns: ["factor_of_safety"] }),
      { status: 409 },
    )));
    await expect(signoff()).resolves.toEqual({
      ok: false, message: "cannot sign off: ...", unknowns: ["factor_of_safety"],
    });
  });
});
