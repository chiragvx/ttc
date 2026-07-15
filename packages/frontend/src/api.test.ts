import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { analyze, analyzeStatus, optimize } from "./api";

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
