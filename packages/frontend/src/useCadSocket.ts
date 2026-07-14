import { useCallback, useEffect, useRef, useState } from "react";
import type { MutationRejected, ParamMutationRequest, ServerMessage, TelemetryDelta } from "./types";

export interface SocketState {
  connected: boolean;
  telemetry: TelemetryDelta | null;
  // exposed so callers can refresh telemetry after a REST-driven change (add/remove a part via
  // instance_ops or the outliner) — those never touch this socket, so the WS's own push alone
  // would leave Mass/CG/Print/Cost stale until the next slider touch (see App.tsx::loadProject).
  setTelemetry: (t: TelemetryDelta | null) => void;
  lastReject: MutationRejected | null;
  // send returns the server's response for THIS request (FIFO-correlated — responses are 1:1 and ordered)
  send: (req: ParamMutationRequest) => Promise<ServerMessage>;
}

// Tier-0 WebSocket client. Sliders call send() fire-and-forget; the chat awaits it for per-delta outcomes.
//
// Reconnects with capped exponential backoff on any close (2026-07-05) — the previous version opened
// the socket once on mount and never retried, so a backend restart, deploy, or transient network drop
// left every future send() rejecting with "socket not open" forever, with no way to recover short of a
// manual page refresh. This was hit live: a chat turn's parameter deltas failed identically 5 times in
// a row with that exact error and never came back.
export function useCadSocket(url = `ws://${location.host}/ws`): SocketState {
  const ws = useRef<WebSocket | null>(null);
  const pending = useRef<Array<{ resolve: (m: ServerMessage) => void; reject: (e: Error) => void }>>([]);
  const reconnectAttempt = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [connected, setConnected] = useState(false);
  const [telemetry, setTelemetry] = useState<TelemetryDelta | null>(null);
  const [lastReject, setLastReject] = useState<MutationRejected | null>(null);

  useEffect(() => {
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      const socket = new WebSocket(url);
      ws.current = socket;
      socket.onopen = () => {
        reconnectAttempt.current = 0;
        setConnected(true);
      };
      socket.onclose = () => {
        setConnected(false);
        // anything still awaiting a reply on this socket will never get one — reject now rather
        // than hanging a chat turn forever (a promise that never settles reads as the same "stuck,
        // not responding" symptom as the earlier reload-storm bug, just from a different cause)
        const waiting = pending.current.splice(0);
        for (const { reject } of waiting) reject(new Error("connection lost"));
        if (stopped) return;
        const delay = Math.min(1000 * 2 ** reconnectAttempt.current, 15000);
        reconnectAttempt.current += 1;
        reconnectTimer.current = setTimeout(connect, delay);
      };
      socket.onmessage = (ev) => {
        const msg = JSON.parse(ev.data) as ServerMessage;
        if (msg.event_type === "PARAMETER_CASCADE_UPDATE") {
          setTelemetry(msg.telemetry_delta);
          setLastReject(null);
        } else {
          setLastReject(msg);
        }
        pending.current.shift()?.resolve(msg);
      };
    };

    connect();
    return () => {
      stopped = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      ws.current?.close();
    };
  }, [url]);

  const send = useCallback((req: ParamMutationRequest) => {
    return new Promise<ServerMessage>((resolve, reject) => {
      const sock = ws.current;
      if (!sock || sock.readyState !== WebSocket.OPEN) {
        reject(new Error("socket not open — reconnecting, please retry in a moment"));
        return;
      }
      pending.current.push({ resolve, reject });
      sock.send(JSON.stringify(req));
    });
  }, []);

  return { connected, telemetry, setTelemetry, lastReject, send };
}
