import "@testing-library/jest-dom/vitest";

// @xyflow/react (EKGGraphView.tsx) uses ResizeObserver internally to track pane/node sizing, which
// jsdom does not implement — a minimal no-op polyfill here (rather than per-test) keeps every test
// file that renders it from having to know this implementation detail.
if (typeof globalThis.ResizeObserver === "undefined") {
  class ResizeObserverPolyfill {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverPolyfill as unknown as typeof ResizeObserver;
}
