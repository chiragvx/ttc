import { useCallback, useRef, useState } from "react";
import { ClarificationCard } from "./ClarificationCard";
import { Composer } from "./Composer";
import { MessageList } from "./MessageList";
import { ProposalCard } from "./ProposalCard";
import { streamChat } from "../api";
import type { LlmSettings } from "../settings";
import type { ChatEvent, ChatMessage, DeltaOutcome, ParameterDelta } from "../types";

interface Props {
  settings: LlmSettings;
  onApply: (deltas: ParameterDelta[]) => Promise<DeltaOutcome[]>;
  onUndo: (outcomes: DeltaOutcome[]) => Promise<void>;
  onOpenSettings: () => void;
  onUserMessage?: (text: string) => void;  // extract any goal/targets from what the user says
}

const uid = () => (crypto?.randomUUID?.() ?? String(Math.random()));

export function Chat({ settings, onApply, onUndo, onOpenSettings, onUserMessage }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [undone, setUndone] = useState<Record<string, boolean>>({});
  const abortRef = useRef<AbortController | null>(null);

  const patch = (id: string, fn: (m: ChatMessage) => ChatMessage) =>
    setMessages((ms) => ms.map((m) => (m.id === id ? fn(m) : m)));

  const send = useCallback(
    async (text: string) => {
      if (streaming) return;
      onUserMessage?.(text);  // fold any stated targets into the goal — works with or without an LLM key
      const user: ChatMessage = { id: uid(), role: "user", text };
      const aid = uid();
      const history = [...messages, user].map((m) => ({ role: m.role, content: m.text }));
      setMessages((ms) => [...ms, user, { id: aid, role: "assistant", text: "", streaming: true }]);
      setStreaming(true);

      const ctrl = new AbortController();
      abortRef.current = ctrl;

      const onEvent = async (e: ChatEvent) => {
        if (e.type === "token") {
          patch(aid, (m) => ({ ...m, text: m.text + e.text }));
        } else if (e.type === "proposal") {
          if (e.deltas.length) {
            const outcomes = await onApply(e.deltas);
            patch(aid, (m) => ({ ...m, outcomes }));
          }
          if (e.clarification || e.suggestions.length) {
            patch(aid, (m) => ({ ...m, clarification: e.clarification, suggestions: e.suggestions }));
          }
        } else if (e.type === "no_llm") {
          patch(aid, (m) => ({ ...m, text: "No LLM configured — add an OpenRouter key in ⚙ settings." }));
        } else if (e.type === "error") {
          patch(aid, (m) => ({ ...m, text: (m.text ? m.text + "\n\n" : "") + `⚠ ${e.message}` }));
        }
      };

      try {
        await streamChat(history, settings, onEvent, ctrl.signal);
      } catch (err) {
        if (!ctrl.signal.aborted) patch(aid, (m) => ({ ...m, text: (m.text || "") + `\n\n⚠ ${String(err)}` }));
      } finally {
        patch(aid, (m) => ({ ...m, streaming: false }));
        setStreaming(false);
        abortRef.current = null;
      }
    },
    [messages, streaming, settings, onApply, onUserMessage],
  );

  const stop = () => abortRef.current?.abort();

  const renderExtras = (m: ChatMessage) => (
    <>
      {m.outcomes && (
        <ProposalCard
          outcomes={m.outcomes}
          undone={!!undone[m.id]}
          onUndo={async () => {
            await onUndo(m.outcomes!);
            setUndone((u) => ({ ...u, [m.id]: true }));
          }}
        />
      )}
      {m.suggestions && m.suggestions.length > 0 && (
        <ClarificationCard suggestions={m.suggestions} onPick={(s) => send(s)} />
      )}
    </>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingBottom: 8, borderBottom: "1px solid #30363d" }}>
        <strong style={{ fontSize: 13 }}>Chat</strong>
        <button onClick={onOpenSettings} title="LLM settings" style={{ background: "none", border: "none", color: "#8b949e", cursor: "pointer", fontSize: 16 }}>
          ⚙
        </button>
      </div>
      <MessageList messages={messages} renderExtras={renderExtras} onExample={send} />
      <Composer streaming={streaming} noKey={!settings.apiKey} onSend={send} onStop={stop} />
    </div>
  );
}
