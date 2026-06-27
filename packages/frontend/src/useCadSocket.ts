import { useCallback, useEffect, useRef, useState } from "react";
import type { CascadeUpdate, MutationRejected, ParamMutationRequest, ServerMessage, TelemetryDelta } from "./types";

export interface SocketState {
  connected: boolean;
  telemetry: TelemetryDelta | null;
  lastReject: MutationRejected | null;
  lastApplied: CascadeUpdate["mutations_applied"];
  send: (req: ParamMutationRequest) => void;
}

// Tier-0 WebSocket client: send slider mutations, receive validated cascades or NACKs.
export function useCadSocket(url = `ws://${location.host}/ws`): SocketState {
  const ws = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [telemetry, setTelemetry] = useState<TelemetryDelta | null>(null);
  const [lastReject, setLastReject] = useState<MutationRejected | null>(null);
  const [lastApplied, setLastApplied] = useState<CascadeUpdate["mutations_applied"]>([]);

  useEffect(() => {
    const socket = new WebSocket(url);
    ws.current = socket;
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onmessage = (ev) => {
      const msg = JSON.parse(ev.data) as ServerMessage;
      if (msg.event_type === "PARAMETER_CASCADE_UPDATE") {
        setTelemetry(msg.telemetry_delta);
        setLastApplied(msg.mutations_applied);
        setLastReject(null);
      } else {
        setLastReject(msg);
      }
    };
    return () => socket.close();
  }, [url]);

  const send = useCallback((req: ParamMutationRequest) => {
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(req));
  }, []);

  return { connected, telemetry, lastReject, lastApplied, send };
}
