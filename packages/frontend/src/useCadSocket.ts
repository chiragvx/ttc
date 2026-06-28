import { useCallback, useEffect, useRef, useState } from "react";
import type { MutationRejected, ParamMutationRequest, ServerMessage, TelemetryDelta } from "./types";

export interface SocketState {
  connected: boolean;
  telemetry: TelemetryDelta | null;
  lastReject: MutationRejected | null;
  // send returns the server's response for THIS request (FIFO-correlated — responses are 1:1 and ordered)
  send: (req: ParamMutationRequest) => Promise<ServerMessage>;
}

// Tier-0 WebSocket client. Sliders call send() fire-and-forget; the chat awaits it for per-delta outcomes.
export function useCadSocket(url = `ws://${location.host}/ws`): SocketState {
  const ws = useRef<WebSocket | null>(null);
  const pending = useRef<Array<(m: ServerMessage) => void>>([]);
  const [connected, setConnected] = useState(false);
  const [telemetry, setTelemetry] = useState<TelemetryDelta | null>(null);
  const [lastReject, setLastReject] = useState<MutationRejected | null>(null);

  useEffect(() => {
    const socket = new WebSocket(url);
    ws.current = socket;
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onmessage = (ev) => {
      const msg = JSON.parse(ev.data) as ServerMessage;
      if (msg.event_type === "PARAMETER_CASCADE_UPDATE") {
        setTelemetry(msg.telemetry_delta);
        setLastReject(null);
      } else {
        setLastReject(msg);
      }
      pending.current.shift()?.(msg);
    };
    return () => socket.close();
  }, [url]);

  const send = useCallback((req: ParamMutationRequest) => {
    return new Promise<ServerMessage>((resolve, reject) => {
      const sock = ws.current;
      if (!sock || sock.readyState !== WebSocket.OPEN) {
        reject(new Error("socket not open"));
        return;
      }
      pending.current.push(resolve);
      sock.send(JSON.stringify(req));
    });
  }, []);

  return { connected, telemetry, lastReject, send };
}
