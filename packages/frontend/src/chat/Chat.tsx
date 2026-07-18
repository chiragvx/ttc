import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ChangesetCard } from "./ChangesetCard";
import { ClarificationCard } from "./ClarificationCard";
import { Composer } from "./Composer";
import { FeatureOpCard } from "./FeatureOpCard";
import { InstanceOpCard } from "./InstanceOpCard";
import { MessageList } from "./MessageList";
import { ProposalCard } from "./ProposalCard";
import { ValidationCard } from "./ValidationCard";
import { summarizeOutcomes } from "./summarizeOutcomes";
import { streamChat } from "../api";
import type { LlmSettings } from "../settings";
import type { ChatEvent, ChatMessage, ConnectionOp, ConnectionOpOutcome, CouplingOp, CouplingOpOutcome, DeltaOutcome, FeatureOp, FeatureOpOutcome, InstanceOp, InstanceOpOutcome, ParameterDelta, ValidationResult } from "../types";

interface Props {
  settings: LlmSettings;
  onApply: (deltas: ParameterDelta[]) => Promise<DeltaOutcome[]>;
  onUndo: (outcomes: DeltaOutcome[]) => Promise<void>;
  onApplyFeatureOp: (op: FeatureOp) => Promise<FeatureOpOutcome>;
  onApplyInstanceOp: (op: InstanceOp) => Promise<InstanceOpOutcome>;
  onApplyConnectionOp: (op: ConnectionOp) => Promise<ConnectionOpOutcome>;  // Phase 1b mate
  onApplyCouplingOp: (op: CouplingOp) => Promise<CouplingOpOutcome>;  // Phase 2b load coupling
  onUndoFeatureOp: (outcome: FeatureOpOutcome) => Promise<FeatureOpOutcome>;
  onUndoInstanceOp: (outcome: InstanceOpOutcome) => Promise<InstanceOpOutcome>;
  // called once after a whole batch of feature_ops/instance_ops finishes applying (a full proposal,
  // or one manual Undo click) — refreshes the outliner/params/viewport/telemetry a single time,
  // never per individual op (see App.tsx::refreshAfterOps for why that matters).
  onOpsApplied: () => Promise<void>;
  // self-check the current assembly against the user's intent (2026-07-19) — geometric always, visual
  // if a vision model is configured. Runs after a turn changes geometry; drives the auto-correct loop.
  onValidate: (intent: string) => Promise<ValidationResult>;
  onOpenSettings: () => void;
  onUserMessage?: (text: string) => void;  // extract any goal/targets from what the user says
  onHoverInstance?: (instanceId: string | null) => void;  // viewport hover marker, shared with Outliner
}

const uid = () => (crypto?.randomUUID?.() ?? String(Math.random()));

// how many times the copilot may auto-correct its own work before handing back to the user — a hard
// cap so a design it can't satisfy never loops forever (or burns tokens indefinitely).
const MAX_AUTO_ROUNDS = 2;

export function Chat({ settings, onApply, onUndo, onApplyFeatureOp, onApplyInstanceOp, onApplyConnectionOp, onApplyCouplingOp, onUndoFeatureOp, onUndoInstanceOp, onOpsApplied, onValidate, onOpenSettings, onUserMessage, onHoverInstance }: Props) {
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
  // self-correct loop state (2026-07-19). autoRound counts corrective rounds in the CURRENT build
  // sequence (reset on every real user message); lastIntent is what validation judges against;
  // pendingCorrection carries a corrective turn to auto-send once streaming settles (fired from an
  // effect, NOT re-entrantly inside send — the same decoupling the viewport-regen fix taught).
  const autoRoundRef = useRef(0);
  const lastIntentRef = useRef("");
  const [pendingCorrection, setPendingCorrection] = useState<string | null>(null);
  const sendRef = useRef<((text: string, isAuto?: boolean) => Promise<void>) | null>(null);
  // SYNCHRONOUS in-flight guard. The `streaming` STATE is a closure value inside send's useCallback,
  // so two invocations of the same send instance in one render tick (a user keypress racing the
  // pendingCorrection effect) both read the same stale `false` and both proceed — two concurrent
  // turns clobbering abortRef and interleaving ops (2026-07-19 review, HIGH). A ref set/checked
  // synchronously at the top of send serializes them; the `streaming` state stays for UI only.
  const streamingRef = useRef(false);

  const patch = (id: string, fn: (m: ChatMessage) => ChatMessage) =>
    setMessages((ms) => ms.map((m) => (m.id === id ? fn(m) : m)));

  const send = useCallback(
    async (text: string, isAuto: boolean = false) => {
      if (streamingRef.current) return;   // synchronous — see streamingRef
      streamingRef.current = true;
      if (!isAuto) {
        // a real user message starts a fresh build sequence: reset the auto-correct budget and record
        // the intent the self-check judges against.
        autoRoundRef.current = 0;
        lastIntentRef.current = text;
      }
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

      // did any op this turn actually APPLY (not merely get proposed)? A fully-rejected proposal
      // changed no geometry, so it must not trigger a /validate call or burn an auto-correct round
      // (2026-07-19 review). Mutated by onEvent below; read after the stream loop.
      let appliedGeometry = false;

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
            if (instanceOpOutcomes.some((o) => o?.status === "APPLIED")) appliedGeometry = true;
            await onOpsApplied();
          }
          if (e.connection_ops?.length) {
            // AFTER instance_ops (both parts must exist), so the mate places the newly-added parts.
            const connOutcomes: (ConnectionOpOutcome | undefined)[] = new Array(e.connection_ops.length).fill(undefined);
            patch(aid, (m) => ({ ...m, connectionOps: e.connection_ops, connectionOpOutcomes: [...connOutcomes] }));
            for (let i = 0; i < e.connection_ops.length; i++) {
              connOutcomes[i] = await onApplyConnectionOp(e.connection_ops[i]);
              patch(aid, (m) => ({ ...m, connectionOpOutcomes: [...connOutcomes] }));
            }
            if (connOutcomes.some((o) => o?.status === "APPLIED")) appliedGeometry = true;
            await onOpsApplied();
          }
          if (e.coupling_ops?.length) {
            // AFTER connection_ops/instance_ops (the target instance must exist), same "propose then
            // auto-apply" boundary as every other op kind.
            const couplingOutcomes: (CouplingOpOutcome | undefined)[] = new Array(e.coupling_ops.length).fill(undefined);
            patch(aid, (m) => ({ ...m, couplingOps: e.coupling_ops, couplingOpOutcomes: [...couplingOutcomes] }));
            for (let i = 0; i < e.coupling_ops.length; i++) {
              couplingOutcomes[i] = await onApplyCouplingOp(e.coupling_ops[i]);
              patch(aid, (m) => ({ ...m, couplingOpOutcomes: [...couplingOutcomes] }));
            }
            if (couplingOutcomes.some((o) => o?.status === "APPLIED")) appliedGeometry = true;
            await onOpsApplied();
          }
          if (e.deltas.length) {
            const outcomes = await onApply(e.deltas);
            patch(aid, (m) => ({ ...m, outcomes }));
            if (outcomes.some((o) => o.status === "APPLIED" || o.status === "APPLIED_ADVISORY")) appliedGeometry = true;
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
            if (featureOpOutcomes.some((o) => o?.status === "APPLIED")) appliedGeometry = true;
            await onOpsApplied();
          }
          if (e.scope_proposal) {
            // Pure display data — no apply loop, no outcomes array (unlike every op kind above).
            patch(aid, (m) => ({ ...m, scopeProposal: e.scope_proposal }));
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
              !m.connectionOps?.length &&
              !m.couplingOps?.length &&
              !m.scopeProposal &&
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
        streamingRef.current = false;
        abortRef.current = null;
      }

      // SELF-CHECK — runs AFTER the stream loop has fully drained (never awaited inside onEvent: doing
      // so parked the SSE reader for the whole /validate round trip — the slow vision call especially —
      // so 'done' never processed and the turn hung, un-cancellable; 2026-07-19 review, HIGH). By here
      // streaming is already false, so the geometry is applied and the UI is responsive while this runs
      // in the background; the card fills in when it returns. Only when geometry actually APPLIED.
      if (appliedGeometry) {
        try {
          const report = await onValidate(lastIntentRef.current);
          patch(aid, (m) => ({ ...m, validation: report }));
          if (!report.ok && autoRoundRef.current < MAX_AUTO_ROUNDS && settings.apiKey) {
            autoRoundRef.current += 1;
            const issues = [...report.geometric.issues, ...(report.visual?.issues ?? [])];
            const lines = issues.map((i) => `- ${i.message}`).join("\n");
            setPendingCorrection(   // the effect fires it once streaming settles, never re-entrantly
              `Self-check of what you just built found problems:\n${lines}\n\n` +
              `Fix them — adjust the parts/params so the design validates. ` +
              `(auto-correction round ${autoRoundRef.current} of ${MAX_AUTO_ROUNDS})`,
            );
          }
        } catch {
          /* validation is best-effort; a failure must never break the chat turn */
        }
      }
    },
    [messages, streaming, settings, onApply, onUserMessage, onValidate,
     onApplyInstanceOp, onApplyFeatureOp, onOpsApplied],
  );

  // keep a ref to the latest `send` so the pendingCorrection effect can fire an auto-correction turn
  // without capturing a stale closure (send is recreated as messages/streaming change).
  sendRef.current = send;

  // Fire a queued auto-correction ONCE the current turn's streaming has settled — decoupled from
  // send's own execution (firing re-entrantly is exactly what froze the viewport in the earlier
  // regen bug). autoRoundRef already capped how many of these can be queued.
  useEffect(() => {
    if (pendingCorrection && !streaming) {
      const text = pendingCorrection;
      setPendingCorrection(null);
      void sendRef.current?.(text, true);
    }
  }, [pendingCorrection, streaming]);

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
    if (m.connectionOps && m.connectionOps.length > 0) {
      sections.push({
        label: "Mates",
        content: (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {m.connectionOps.map((op, i) => {
              const o = m.connectionOpOutcomes?.[i];
              const ok = o?.status === "APPLIED";
              const color = o == null ? "#8b949e" : ok ? "#3fb950" : "#f85149";
              const label = op.op === "add_connection"
                ? `${op.a_instance}.${op.a_interface} ↔ ${op.b_instance}.${op.b_interface}`
                : `remove ${op.id}`;
              return (
                <div key={i} style={{ fontSize: 11, color: "#c9d1d9" }}>
                  <span style={{ color }}>{o == null ? "…" : ok ? "✓" : "✕"}</span> {label}
                  {o && !ok && o.message ? <span style={{ color: "#f85149" }}> — {o.message}</span> : null}
                </div>
              );
            })}
          </div>
        ),
      });
    }
    if (m.couplingOps && m.couplingOps.length > 0) {
      sections.push({
        label: "Loads",
        content: (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {m.couplingOps.map((op, i) => {
              const o = m.couplingOpOutcomes?.[i];
              const ok = o?.status === "APPLIED";
              const color = o == null ? "#8b949e" : ok ? "#3fb950" : "#f85149";
              const label = op.op === "add_coupling"
                ? `${op.target_instance} <- ${op.relation}`
                : `remove ${op.id}`;
              return (
                <div key={i} style={{ fontSize: 11, color: "#c9d1d9" }}>
                  <span style={{ color }}>{o == null ? "…" : ok ? "✓" : "✕"}</span> {label}
                  {o && !ok && o.message ? <span style={{ color: "#f85149" }}> — {o.message}</span> : null}
                </div>
              );
            })}
          </div>
        ),
      });
    }
    if (m.scopeProposal) {
      const scope = m.scopeProposal;
      sections.push({
        label: "Scope",
        content: (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ fontSize: 11, color: "#c9d1d9" }}>{scope.goal}</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {scope.parts.map((p, i) => (
                <div key={i} style={{ fontSize: 11, color: "#c9d1d9" }}>
                  <strong>{p.role}</strong> — {p.subsystem_type} × {p.count}
                  {p.operating_conditions.length > 0 ? ` (${p.operating_conditions.join(", ")})` : ""}
                  {p.rationale ? <div style={{ color: "#8b949e" }}>{p.rationale}</div> : null}
                </div>
              ))}
            </div>
            {scope.out_of_scope.length > 0 && (
              <div style={{ fontSize: 11, color: "#8b949e" }}>
                Out of scope: {scope.out_of_scope.join(", ")}
              </div>
            )}
            {scope.open_questions.length > 0 && (
              <div style={{ fontSize: 11, color: "#8b949e" }}>
                Open questions:
                <ul style={{ margin: "2px 0 0 16px", padding: 0 }}>
                  {scope.open_questions.map((q, i) => (
                    <li key={i}>{q}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ),
      });
    }
    return (
      <>
        <ChangesetCard sections={sections} />
        {m.validation && <ValidationCard result={m.validation} />}
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
