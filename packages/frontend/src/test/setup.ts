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

// chat/MessageList.tsx calls Element.scrollIntoView on every message-list update (auto-scroll to the
// newest message) — jsdom does not implement it either, same class of gap as ResizeObserver above; a
// missing polyfill throws inside a passive effect and crashes the whole render tree in a test.
if (typeof Element.prototype.scrollIntoView === "undefined") {
  Element.prototype.scrollIntoView = () => {};
}
