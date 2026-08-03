import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useCadSocket } from "./useCadSocket";

// Minimal WebSocket mock — captures every instance the hook creates so a test can drive
// onopen/onclose directly, the same "stub the global, inspect what the code under test did with it"
// style api.test.ts uses for fetch (vi.stubGlobal), just applied to WebSocket instead. There is no
// real network here at all; jsdom has no WebSocket implementation of its own for this to conflict with.
class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: MockWebSocket[] = [];

  readyState: number = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  send = vi.fn();
  close = vi.fn();

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  // test helpers — simulate the server side of the handshake/drop
  triggerOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }
  triggerClose() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }
}

function latest(): MockWebSocket {
  return MockWebSocket.instances[MockWebSocket.instances.length - 1];
}

beforeEach(() => {
  MockWebSocket.instances = [];
  vi.stubGlobal("WebSocket", MockWebSocket);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

// Covers the capped-exponential-backoff reconnect loop added 2026-07-05 (see useCadSocket.ts's own
// onclose comment: a dropped socket used to never retry, wedging every future send() forever). The
// reconnect attempt counter is a private ref, not part of SocketState, so it's verified indirectly
// through the one thing it's actually FOR: how long the hook waits before opening the next socket.
describe("useCadSocket reconnect backoff", () => {
  it("grows the reconnect delay exponentially across successive closes (1s, 2s, 4s, 8s...)", () => {
    renderHook(() => useCadSocket("ws://test/ws"));
    expect(MockWebSocket.instances).toHaveLength(1);

    const expectedDelays = [1000, 2000, 4000, 8000];
    for (const delay of expectedDelays) {
      act(() => {
        latest().triggerClose();
      });
      const countBefore = MockWebSocket.instances.length;

      // one tick short of the expected delay: no reconnect yet
      act(() => {
        vi.advanceTimersByTime(delay - 1);
      });
      expect(MockWebSocket.instances).toHaveLength(countBefore);

      // the final millisecond fires the reconnect
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(MockWebSocket.instances).toHaveLength(countBefore + 1);
    }
  });

  it("caps the reconnect delay at 15s instead of letting it grow unbounded", () => {
    renderHook(() => useCadSocket("ws://test/ws"));

    // walk through enough consecutive closes that the naive 1000 * 2^attempt formula would already
    // be past 15s (2^4 * 1000 = 16000) — the cap must kick in here, and stay there on a later close too.
    const delaysBeforeCap = [1000, 2000, 4000, 8000];
    for (const delay of delaysBeforeCap) {
      act(() => {
        latest().triggerClose();
        vi.advanceTimersByTime(delay);
      });
    }

    // next close would naively want 16000ms — must be capped to 15000ms
    act(() => {
      latest().triggerClose();
    });
    const countBefore = MockWebSocket.instances.length;
    act(() => {
      vi.advanceTimersByTime(14999);
    });
    expect(MockWebSocket.instances).toHaveLength(countBefore); // not yet — still capped, not fired early
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(MockWebSocket.instances).toHaveLength(countBefore + 1);

    // one more close beyond the cap (naive formula: 32000ms) must ALSO stay capped at 15000ms, not
    // keep climbing
    act(() => {
      latest().triggerClose();
    });
    const countBefore2 = MockWebSocket.instances.length;
    act(() => {
      vi.advanceTimersByTime(15000);
    });
    expect(MockWebSocket.instances).toHaveLength(countBefore2 + 1);
  });

  it("resets the reconnect attempt counter to zero after a successful open, so the next drop starts back at 1s", () => {
    renderHook(() => useCadSocket("ws://test/ws"));

    // first drop: burns through a couple of backoff steps to move the counter off zero
    act(() => {
      latest().triggerClose();
      vi.advanceTimersByTime(1000); // -> reconnect #2 opens
    });
    act(() => {
      latest().triggerClose();
      vi.advanceTimersByTime(2000); // -> reconnect #3 opens
    });

    // this time the reconnect succeeds — onopen must zero the counter
    act(() => {
      latest().triggerOpen();
    });

    // a fresh close now must wait only 1000ms again, not 4000ms (which is what continued exponential
    // growth from attempt=2 would demand)
    act(() => {
      latest().triggerClose();
    });
    const countBefore = MockWebSocket.instances.length;
    act(() => {
      vi.advanceTimersByTime(999);
    });
    expect(MockWebSocket.instances).toHaveLength(countBefore); // not yet at 999ms
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(MockWebSocket.instances).toHaveLength(countBefore + 1); // fires right at 1000ms, proving the reset
  });
});
