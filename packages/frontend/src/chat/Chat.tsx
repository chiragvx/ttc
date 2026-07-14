import { useCallback, useRef, useState, type ReactNode } from "react";
import { ChangesetCard } from "./ChangesetCard";
import { ClarificationCard } from "./ClarificationCard";
import { Composer } from "./Composer";
import { FeatureOpCard } from "./FeatureOpCard";
import { InstanceOpCard } from "./InstanceOpCard";
import { MessageList } from "./MessageList";
import { ProposalCard } from "./ProposalCard";
import { summarizeOutcomes } from "./summarizeOutcomes";
import { streamChat } from "../api";
import type { LlmSettings } from "../settings";
import type { ChatEvent, ChatMessage, DeltaOutcome, FeatureOp, FeatureOpOutcome, InstanceOp, InstanceOpOutcome, ParameterDelta } from "../types";

interface Props {
  settings: LlmSettings;
  onApply: (deltas: ParameterDelta[]) => Promise<DeltaOutcome[]>;
  onUndo: (outcomes: DeltaOutcome[]) => Promise<void>;
  onApplyFeatureOp: (op: FeatureOp) => Promise<FeatureOpOutcome>;
  onApplyInstanceOp: (op: InstanceOp) => Promise<InstanceOpOutcome>;
  onUndoFeatureOp: (outcome: FeatureOpOutcome) => Promise<FeatureOpOutcome>;
  onUndoInstanceOp: (outcome: InstanceOpOutcome) => Promise<InstanceOpOutcome>;
  // called once after a whole batch of feature_ops/instance_ops finishes applying (a full proposal,
  // or one manual Undo click) — refreshes the outliner/params/viewport/telemetry a single time,
  // never per individual op (see App.tsx::refreshAfterOps for why that matters).
  onOpsApplied: () => Promise<void>;
  onOpenSettings: () => void;
  onUserMessage?: (text: string) => void;  // extract any goal/targets from what the user says
  onHoverInstance?: (instanceId: string | null) => void;  // viewport hover marker, shared with Outliner
}

const uid = () => (crypto?.randomUUID?.() ?? String(Math.random()));

export function Chat({ settings, onApply, onUndo, onApplyFeatureOp, onApplyInstanceOp, onUndoFeatureOp, onUndoInstanceOp, onOpsApplied, onOpenSettings, onUserMessage, onHoverInstance }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [undone, setUndone] = useState<Record<string, boolean>>({});
  // feature_ops/instance_ops are auto-applied like deltas (packages/agents/CLAUDE.md's updated
  // policy — every proposal applies immediately, every applied item carries an Undo). These track
  // which individual items (keyed `${messageId}:${index}`) have already been undone.
  const [undoneFeatureOps, setUndoneFeatureOps] = useState<Record<string, boolean>>({});
  const [undoneInstanceOps, setUndoneInstanceOps] = useState<Record<string, boolean>>({});
  // Undo can itself be REJECTED by the rules validator (e.g. undoing an add_instance whose part has
  // since grown children) — this must never be silently treated as success. Keyed the same way.
  const [undoErrors, setUndoErrors] = useState<Record<string, string>>({});
  const abortRef = useRef<AbortController | null>(null);

  const patch = (id: string, fn: (m: ChatMessage) => ChatMessage) =>
    setMessages((ms) => ms.map((m) => (m.id === id ? fn(m) : m)));

  const send = useCallback(
    async (text: string) => {
      if (streaming) return;
      onUserMessage?.(text);  // fold any stated targets into the goal — works with or without an LLM key
      const user: ChatMessage = { id: uid(), role: "user", text };
      const aid = uid();
      // an assistant turn's outcome summary (applied/rejected ids + reasons) rides along in the
      // history sent back, invisible in the UI (the cards already show it) — otherwise a REJECTED
      // op just vanishes from what the model can see next turn, with no way to learn why or to
      // target the real id a successful add_instance minted (see summarizeOutcomes.ts).
      const history = [...messages, user].map((m) => {
        const summary = m.role === "assistant" ? summarizeOutcomes(m) : null;
        return { role: m.role, content: summary ? `${m.text}\n\n${summary}` : m.text };
      });
      setMessages((ms) => [...ms, user, { id: aid, role: "assistant", text: "", streaming: true }]);
      setStreaming(true);

      const ctrl = new AbortController();
      abortRef.current = ctrl;

      const onEvent = async (e: ChatEvent) => {
        if (e.type === "token") {
          patch(aid, (m) => ({ ...m, text: m.text + e.text }));
        } else if (e.type === "proposal") {
          // instance_ops FIRST: a delta/feature_op in this SAME proposal may target an instance_id
          // that only exists once its own add_instance has landed (packages/ledger/apply.py resolves
          // a delta against instances.<id>.params.<name> for an id not yet in the ledger to a clean
          // REJECT) — this is what lets "add N parts, each with a custom param value" work in one
          // turn. deltas next, feature_ops last (a cut may also want to target a part instance_ops
          // just added).
          if (e.instance_ops.length) {
            const instanceOpOutcomes: (InstanceOpOutcome | undefined)[] = new Array(e.instance_ops.length).fill(undefined);
            patch(aid, (m) => ({ ...m, instanceOps: e.instance_ops, instanceOpOutcomes: [...instanceOpOutcomes] }));
            for (let i = 0; i < e.instance_ops.length; i++) {
              instanceOpOutcomes[i] = await onApplyInstanceOp(e.instance_ops[i]);
              patch(aid, (m) => ({ ...m, instanceOpOutcomes: [...instanceOpOutcomes] }));
            }
            await onOpsApplied();
          }
          if (e.deltas.length) {
            const outcomes = await onApply(e.deltas);
            patch(aid, (m) => ({ ...m, outcomes }));
          }
          if (e.feature_ops.length) {
            // sequential, not Promise.all — each op is validated against the ledger state the
            // PRIOR op just left, so they must land in order (mirrors onApply's own delta loop).
            // The full planned list is shown immediately (so a big batch never looks like nothing
            // is happening) and each row's outcome fills in as it actually completes — a proposal
            // with 20-30 ops used to render NOTHING until the entire sequential batch finished,
            // which read as a hang (see App.tsx::refreshAfterOps for the other half of this fix).
            const featureOpOutcomes: (FeatureOpOutcome | undefined)[] = new Array(e.feature_ops.length).fill(undefined);
            patch(aid, (m) => ({ ...m, featureOps: e.feature_ops, featureOpOutcomes: [...featureOpOutcomes] }));
            for (let i = 0; i < e.feature_ops.length; i++) {
              featureOpOutcomes[i] = await onApplyFeatureOp(e.feature_ops[i]);
              patch(aid, (m) => ({ ...m, featureOpOutcomes: [...featureOpOutcomes] }));
            }
            await onOpsApplied();
          }
          if (e.clarification || e.suggestions.length) {
            patch(aid, (m) => ({ ...m, clarification: e.clarification, suggestions: e.suggestions }));
          }
        } else if (e.type === "no_llm") {
          patch(aid, (m) => ({ ...m, text: "No LLM configured — add an OpenRouter key in ⚙ settings." }));
        } else if (e.type === "error") {
          patch(aid, (m) => ({ ...m, text: (m.text ? m.text + "\n\n" : "") + `⚠ ${e.message}` }));
        } else if (e.type === "done") {
          // Defense-in-depth backstop (see FIX 1 in the investigation this responds to): the backend
          // now always yields an explicit error for an otherwise-empty turn, but if some edge case it
          // doesn't anticipate still slips through, never leave the bubble permanently blank with no
          // indication anything happened.
          patch(aid, (m) => {
            const nothingAdded =
              !m.text &&
              !m.outcomes?.length &&
              !m.featureOps?.length &&
              !m.instanceOps?.length &&
              !m.clarification &&
              !m.suggestions?.length;
            return nothingAdded
              ? { ...m, text: "(no response was generated for that message — try again)" }
              : m;
          });
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

  const renderExtras = (m: ChatMessage) => {
    const sections: { label: string; content: ReactNode }[] = [];
    if (m.outcomes) {
      sections.push({
        label: "Parameters",
        content: (
          <ProposalCard
            outcomes={m.outcomes}
            undone={!!undone[m.id]}
            onHover={onHoverInstance}
            onUndo={async () => {
              await onUndo(m.outcomes!);
              setUndone((u) => ({ ...u, [m.id]: true }));
            }}
          />
        ),
      });
    }
    if (m.featureOps && m.featureOps.length > 0) {
      sections.push({
        label: "Cuts",
        content: (
          <FeatureOpCard
            ops={m.featureOps}
            outcomes={m.featureOpOutcomes ?? []}
            onHover={onHoverInstance}
            undone={Object.fromEntries(
              m.featureOps.map((_, i) => [i, !!undoneFeatureOps[`${m.id}:fo:${i}`]]),
            )}
            undoError={Object.fromEntries(
              m.featureOps.map((_, i) => [i, undoErrors[`${m.id}:fo:${i}`]]),
            )}
            onUndo={async (i) => {
              const key = `${m.id}:fo:${i}`;
              const result = await onUndoFeatureOp(m.featureOpOutcomes![i]!);
              if (result.status === "APPLIED") {
                setUndoneFeatureOps((s) => ({ ...s, [key]: true }));
                setUndoErrors((s) => { const { [key]: _drop, ...rest } = s; return rest; });
                await onOpsApplied();
              } else {
                setUndoErrors((s) => ({ ...s, [key]: result.reason || "rejected" }));
              }
            }}
          />
        ),
      });
    }
    if (m.instanceOps && m.instanceOps.length > 0) {
      sections.push({
        label: "Parts",
        content: (
          <InstanceOpCard
            ops={m.instanceOps}
            outcomes={m.instanceOpOutcomes ?? []}
            onHover={onHoverInstance}
            undone={Object.fromEntries(
              m.instanceOps.map((_, i) => [i, !!undoneInstanceOps[`${m.id}:io:${i}`]]),
            )}
            undoError={Object.fromEntries(
              m.instanceOps.map((_, i) => [i, undoErrors[`${m.id}:io:${i}`]]),
            )}
            onUndo={async (i) => {
              const key = `${m.id}:io:${i}`;
              const result = await onUndoInstanceOp(m.instanceOpOutcomes![i]!);
              if (result.status === "APPLIED") {
                setUndoneInstanceOps((s) => ({ ...s, [key]: true }));
                setUndoErrors((s) => { const { [key]: _drop, ...rest } = s; return rest; });
                await onOpsApplied();
              } else {
                setUndoErrors((s) => ({ ...s, [key]: result.reason || "rejected" }));
              }
            }}
          />
        ),
      });
    }
    return (
      <>
        <ChangesetCard sections={sections} />
        {m.suggestions && m.suggestions.length > 0 && (
          <ClarificationCard suggestions={m.suggestions} onPick={(s) => send(s)} />
        )}
      </>
    );
  };

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
