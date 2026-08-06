import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ChangesetCard } from "./ChangesetCard";
import { ClarificationCard } from "./ClarificationCard";
import { Composer } from "./Composer";
import { FeatureOpCard } from "./FeatureOpCard";
import { InstanceOpCard } from "./InstanceOpCard";
import { MessageList } from "./MessageList";
import { ProposalCard } from "./ProposalCard";
import { ResearchCard } from "./ResearchCard";
import { ValidationCard } from "./ValidationCard";
import { buildChatContent } from "./buildChatContent";
import { buildCorrectionMessage, NO_PRIOR_ATTEMPT, type PriorAttempt } from "./buildCorrectionMessage";
import { exportConversationToMarkdown, triggerMarkdownDownload } from "./exportConversation";
import { shouldAutoCorrect } from "./shouldAutoCorrect";
import { summarizeOutcomes } from "./summarizeOutcomes";
import { fetchBlueprintDataUrl, fetchDesignReport, fetchModelVisionCapable, streamChat } from "../api";
import type { LlmSettings } from "../settings";
import type { ChatEvent, ChatMessage, ConnectionOp, ConnectionOpOutcome, CouplingOp, CouplingOpOutcome, DeltaOutcome, EnvelopeOp, EnvelopeOpOutcome, FeatureOp, FeatureOpOutcome, FitOp, FitOpOutcome, InstanceOp, InstanceOpOutcome, JoinAnnotationOp, JoinAnnotationOpOutcome, ParameterDelta, RegionOp, RegionOpOutcome, ValidationResult } from "../types";

interface Props {
  settings: LlmSettings;
  onApply: (deltas: ParameterDelta[]) => Promise<DeltaOutcome[]>;
  onUndo: (outcomes: DeltaOutcome[]) => Promise<{ ok: boolean; reason?: string }>;
  onApplyFeatureOp: (op: FeatureOp) => Promise<FeatureOpOutcome>;
  onApplyInstanceOp: (op: InstanceOp) => Promise<InstanceOpOutcome>;
  onApplyConnectionOp: (op: ConnectionOp) => Promise<ConnectionOpOutcome>;  // Phase 1b mate
  onApplyCouplingOp: (op: CouplingOp) => Promise<CouplingOpOutcome>;  // Phase 2b load coupling
  onApplyFitOp: (op: FitOp) => Promise<FitOpOutcome>;  // 2026-07-27 fitted-dimension binding
  onApplyEnvelopeOp: (op: EnvelopeOp) => Promise<EnvelopeOpOutcome>;  // 2026-08-06 housing wrap/unwrap/resync (gearbox-housing-generation initiative)
  onApplyJoinAnnotationOp: (op: JoinAnnotationOp) => Promise<JoinAnnotationOpOutcome>;  // 2026-07-27 semantic join annotation (BOM-only, never touches geometry)
  onApplyRegionOp: (op: RegionOp) => Promise<RegionOpOutcome>;  // 2026-08-04 keep-out/keep-in region annotation, checked by the geometric self-check
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

export function Chat({ settings, onApply, onUndo, onApplyFeatureOp, onApplyInstanceOp, onApplyConnectionOp, onApplyCouplingOp, onApplyFitOp, onApplyEnvelopeOp, onApplyJoinAnnotationOp, onApplyRegionOp, onUndoFeatureOp, onUndoInstanceOp, onOpsApplied, onValidate, onOpenSettings, onUserMessage, onHoverInstance }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [undone, setUndone] = useState<Record<string, boolean>>({});
  const [reportError, setReportError] = useState<string | null>(null);
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
  // Whether the MOST RECENT self-check report came back unresolved (`ok === false`) — set at the
  // bottom of the self-check block below, right after `onValidate` resolves. A pure-prose turn (a
  // scope/clarification reply that applies zero ops) leaves `appliedGeometry` false, which used to
  // mean the self-check silently never re-ran and any issues the PREVIOUS report already found were
  // never resurfaced — the conversation just went quiet on a design that was still broken (2026-08-05
  // root-cause #4). Read alongside `appliedGeometry` at the self-check trigger below so a known-
  // unresolved state keeps getting re-checked even on a turn that changed no geometry.
  const lastReportUnresolvedRef = useRef(false);
  const [pendingCorrection, setPendingCorrection] = useState<string | null>(null);
  const sendRef = useRef<((text: string, isAuto?: boolean) => Promise<void>) | null>(null);
  // SYNCHRONOUS in-flight guard. The `streaming` STATE is a closure value inside send's useCallback,
  // so two invocations of the same send instance in one render tick (a user keypress racing the
  // pendingCorrection effect) both read the same stale `false` and both proceed — two concurrent
  // turns clobbering abortRef and interleaving ops (2026-07-19 review, HIGH). A ref set/checked
  // synchronously at the top of send serializes them; the `streaming` state stays for UI only.
  const streamingRef = useRef(false);
  // Whether the CONFIGURED model can take an image in its message content -- resolved from
  // OpenRouter's live model registry, never assumed (fetchModelVisionCapable), and re-checked
  // whenever the model changes in Settings. Defaults to false until resolved: an auto-correction
  // turn (below) must never attach an image to what may be a text-only model's request.
  const [visionCapable, setVisionCapable] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setVisionCapable(false);
    fetchModelVisionCapable(settings.model)
      .then((capable) => { if (!cancelled) setVisionCapable(capable); })
      .catch(() => { if (!cancelled) setVisionCapable(false); });
    return () => { cancelled = true; };
  }, [settings.model]);

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
      // Render-in-the-Loop (2026-08-05): only meaningful on an auto-correction turn (isAuto) -- the
      // PRECEDING assistant message (the one the self-check below just ran against) may already
      // carry a blueprintImage, patched in BEFORE any correction is queued (see the appliedGeometry
      // block below) precisely so it's already sitting in `messages` by the time a queued correction
      // gets here. Attaching it lets the SAME model that placed the parts see its own render
      // directly, instead of relaying a second model's text summary.
      const priorBlueprintImage = isAuto ? messages[messages.length - 1]?.blueprintImage : undefined;
      const history = [...messages, user].map((m, i) => {
        const summary = m.role === "assistant" ? summarizeOutcomes(m) : null;
        const msgText = summary ? `${m.text}\n\n${summary}` : m.text;
        // the LAST entry ONLY (the message just added for THIS turn) may get multimodal content --
        // every other entry (all past turns, and any non-auto user message) keeps its existing
        // plain-string content, unchanged.
        const content = i === messages.length && priorBlueprintImage
          ? buildChatContent(msgText, priorBlueprintImage, visionCapable)
          : msgText;
        return { role: m.role, content };
      });
      setMessages((ms) => [...ms, user, { id: aid, role: "assistant", text: "", streaming: true }]);
      setStreaming(true);

      const ctrl = new AbortController();
      abortRef.current = ctrl;

      // did any op this turn actually APPLY (not merely get proposed)? A fully-rejected proposal
      // changed no geometry, so it must not trigger a /validate call or burn an auto-correct round
      // (2026-07-19 review). Mutated by onEvent below; read after the stream loop.
      let appliedGeometry = false;
      // every op kind THIS turn proposed (regardless of outcome) -- if this turn is itself a
      // correction attempt and the self-check still fails afterward, the NEXT correction round's
      // message needs to know what was just tried, so it can tell the model "that exact fix didn't
      // work, don't repeat it" instead of silently reissuing it (2026-07-26 live repro, confirmed
      // twice: an identical move_instance retried verbatim across both correction rounds on the
      // cubesat test, and an identical remove_instance retried verbatim on the soldering-stand test
      // -- both burned the entire auto-correct budget on a pure no-op). Originally instance_ops only;
      // 2026-08-03 extended to deltas/feature_ops/connection_ops/coupling_ops too -- none of those op
      // kinds are any less retriable-verbatim than an instance_op, so none of them get a pass.
      const thisTurnDeltas: ParameterDelta[] = [];
      const thisTurnFeatureOps: FeatureOp[] = [];
      const thisTurnInstanceOps: InstanceOp[] = [];
      const thisTurnConnectionOps: ConnectionOp[] = [];
      const thisTurnCouplingOps: CouplingOp[] = [];
      // Tracked for the same reason as the accumulators above, but NOT YET threaded into
      // `priorAttempt`/`PriorAttempt` below (buildCorrectionMessage.ts, owned by a different file in
      // this session) — a repeated identical region_ops retry across correction rounds isn't called
      // out to the model yet the way a repeated delta/feature_op/instance_op/connection_op is. Kept
      // here so that wiring is a one-line addition once PriorAttempt grows a regionOps field.
      const thisTurnRegionOps: RegionOp[] = [];

      const onEvent = async (e: ChatEvent) => {
        if (e.type === "token") {
          patch(aid, (m) => ({ ...m, text: m.text + e.text }));
        } else if (e.type === "research") {
          // Fires BEFORE any token/proposal event, at most once per turn (see the backend's /chat
          // handler) — pure display data, same as scope_proposal below: no apply loop, no outcomes.
          const { type: _type, ...finding } = e;
          patch(aid, (m) => ({ ...m, researchFinding: finding }));
        } else if (e.type === "proposal") {
          // instance_ops FIRST: a delta/feature_op in this SAME proposal may target an instance_id
          // that only exists once its own add_instance has landed (packages/ledger/apply.py resolves
          // a delta against instances.<id>.params.<name> for an id not yet in the ledger to a clean
          // REJECT) — this is what lets "add N parts, each with a custom param value" work in one
          // turn. deltas next, feature_ops last (a cut may also want to target a part instance_ops
          // just added).
          if (e.instance_ops.length) {
            thisTurnInstanceOps.push(...e.instance_ops);
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
            thisTurnConnectionOps.push(...e.connection_ops);
            const connOutcomes: (ConnectionOpOutcome | undefined)[] = new Array(e.connection_ops.length).fill(undefined);
            patch(aid, (m) => ({ ...m, connectionOps: e.connection_ops, connectionOpOutcomes: [...connOutcomes] }));
            for (let i = 0; i < e.connection_ops.length; i++) {
              connOutcomes[i] = await onApplyConnectionOp(e.connection_ops[i]);
              patch(aid, (m) => ({ ...m, connectionOpOutcomes: [...connOutcomes] }));
            }
            if (connOutcomes.some((o) => o?.status === "APPLIED")) appliedGeometry = true;
            await onOpsApplied();
          }
          if (e.envelope_ops?.length) {
            // AFTER instance_ops/connection_ops (2026-08-06): wrap_group needs the housing instance
            // to already exist and the group it wraps to be a REAL, mate-connected cluster — see
            // packages/agents/prompt_builder.py::_housing_pacing_section, the mechanism this closes
            // the loop for. Sets appliedGeometry: wrap_group mutates the housing's own `wraps` list
            // AND (via the backend's post-apply derivation hook) can write the housing's derived
            // dimensions as ordinary ParameterDeltas in the SAME request when no async queue is
            // configured — either way the self-check (envelope_missing/envelope_drift,
            // packages/truth_plane/validate.py) needs to re-run against the new state.
            const envelopeOutcomes: (EnvelopeOpOutcome | undefined)[] = new Array(e.envelope_ops.length).fill(undefined);
            patch(aid, (m) => ({ ...m, envelopeOps: e.envelope_ops, envelopeOpOutcomes: [...envelopeOutcomes] }));
            for (let i = 0; i < e.envelope_ops.length; i++) {
              envelopeOutcomes[i] = await onApplyEnvelopeOp(e.envelope_ops[i]);
              patch(aid, (m) => ({ ...m, envelopeOpOutcomes: [...envelopeOutcomes] }));
            }
            if (envelopeOutcomes.some((o) => o?.status === "APPLIED")) appliedGeometry = true;
            await onOpsApplied();
          }
          if (e.region_ops?.length) {
            // AFTER instance_ops (the host must exist). A Region is a pure geometric ANNOTATION (it
            // derives nothing and nothing derives it, packages/ledger/schema.py::Region) — but UNLIKE
            // join_annotation_ops below, it IS read by the geometric self-check
            // (packages/truth_plane/validate.py's "region" issue flags another part intruding on a
            // keep_out box), so this still sets appliedGeometry so /validate actually re-runs after
            // this turn. This is deliberate: the keepout_mm lesson (packages/subsystems/base.py's own
            // zero-adopter keepout mechanism) is that a keep-out mechanism nothing ever wires to a
            // live check is dead plumbing — this is what makes Region a real, checked mechanism.
            thisTurnRegionOps.push(...e.region_ops);
            const regionOutcomes: (RegionOpOutcome | undefined)[] = new Array(e.region_ops.length).fill(undefined);
            patch(aid, (m) => ({ ...m, regionOps: e.region_ops, regionOpOutcomes: [...regionOutcomes] }));
            for (let i = 0; i < e.region_ops.length; i++) {
              regionOutcomes[i] = await onApplyRegionOp(e.region_ops[i]);
              patch(aid, (m) => ({ ...m, regionOpOutcomes: [...regionOutcomes] }));
            }
            if (regionOutcomes.some((o) => o?.status === "APPLIED")) appliedGeometry = true;
            await onOpsApplied();
          }
          if (e.coupling_ops?.length) {
            // AFTER connection_ops/instance_ops (the target instance must exist), same "propose then
            // auto-apply" boundary as every other op kind.
            thisTurnCouplingOps.push(...e.coupling_ops);
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
            thisTurnDeltas.push(...e.deltas);
            const outcomes = await onApply(e.deltas);
            patch(aid, (m) => ({ ...m, outcomes }));
            if (outcomes.some((o) => o.status === "APPLIED" || o.status === "APPLIED_ADVISORY")) appliedGeometry = true;
          }
          if (e.fit_ops?.length) {
            // AFTER deltas (2026-07-27): compute_fit derives the connector's dimension from the
            // host's CURRENT cross-section, computed ONCE at wire time — a fit applied before this
            // turn's own deltas resize the host would derive against its stale default and be
            // drifted the instant it's created. Same "propose then auto-apply" boundary otherwise.
            const fitOutcomes: (FitOpOutcome | undefined)[] = new Array(e.fit_ops.length).fill(undefined);
            patch(aid, (m) => ({ ...m, fitOps: e.fit_ops, fitOpOutcomes: [...fitOutcomes] }));
            for (let i = 0; i < e.fit_ops.length; i++) {
              fitOutcomes[i] = await onApplyFitOp(e.fit_ops[i]);
              patch(aid, (m) => ({ ...m, fitOpOutcomes: [...fitOutcomes] }));
            }
            if (fitOutcomes.some((o) => o?.status === "APPLIED")) appliedGeometry = true;
            await onOpsApplied();
          }
          if (e.join_annotation_ops?.length) {
            // Purely semantic BOM data (bolted/press_fit/welded/adhesive/custom) — never touches
            // geometry (contrast fit_ops just above; see packages/ledger/schema.py::JoinAnnotation),
            // but same "propose then auto-apply" boundary as every other op kind for a consistent UX.
            const joinAnnotationOutcomes: (JoinAnnotationOpOutcome | undefined)[] = new Array(e.join_annotation_ops.length).fill(undefined);
            patch(aid, (m) => ({ ...m, joinAnnotationOps: e.join_annotation_ops, joinAnnotationOpOutcomes: [...joinAnnotationOutcomes] }));
            for (let i = 0; i < e.join_annotation_ops.length; i++) {
              joinAnnotationOutcomes[i] = await onApplyJoinAnnotationOp(e.join_annotation_ops[i]);
              patch(aid, (m) => ({ ...m, joinAnnotationOpOutcomes: [...joinAnnotationOutcomes] }));
            }
            // No appliedGeometry flag here — a JoinAnnotation never touches geometry or resets an
            // engineer sign-off, unlike every op kind above.
            await onOpsApplied();
          }
          if (e.feature_ops.length) {
            // sequential, not Promise.all — each op is validated against the ledger state the
            // PRIOR op just left, so they must land in order (mirrors onApply's own delta loop).
            // The full planned list is shown immediately (so a big batch never looks like nothing
            // is happening) and each row's outcome fills in as it actually completes — a proposal
            // with 20-30 ops used to render NOTHING until the entire sequential batch finished,
            // which read as a hang (see App.tsx::refreshAfterOps for the other half of this fix).
            thisTurnFeatureOps.push(...e.feature_ops);
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
              !m.fitOps?.length &&
              !m.envelopeOps?.length &&
              !m.joinAnnotationOps?.length &&
              !m.regionOps?.length &&
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
      // in the background; the card fills in when it returns. Runs when THIS turn applied geometry, OR
      // (2026-08-05 root-cause #4) when the MOST RECENT self-check report was still unresolved -- a
      // pure-prose turn (e.g. a scope/clarification reply that applies zero ops) must not let a
      // previously-reported, still-outstanding issue go quiet just because nothing new was applied.
      // Re-running here checks the CURRENT ledger state either way: the issues are still there and get
      // resurfaced/auto-corrected again up to the existing MAX_AUTO_ROUNDS cap below, or they're
      // coincidentally already fixed and the report now comes back clean.
      if (appliedGeometry || lastReportUnresolvedRef.current) {
        try {
          const report = await onValidate(lastIntentRef.current);
          patch(aid, (m) => ({ ...m, validation: report }));
          lastReportUnresolvedRef.current = !report.ok;

          // Render-in-the-loop visibility (2026-08-05): attach the SAME blueprint image the
          // self-check just judged to THIS assistant message, for EVERY geometry-changing turn --
          // not gated on shouldAutoCorrect below, since the user wants to see the render whether or
          // not the self-check found anything, so they can visually verify placement/clipping
          // themselves and reach for the existing Stop button once a correction round is actually
          // streaming (no new pause/confirm gate -- explicitly out of scope). Sequenced BEFORE the
          // shouldAutoCorrect check/setPendingCorrection below, in its OWN try/catch, so (a) its
          // patch lands in `messages` before a queued correction's history-build reads
          // priorBlueprintImage above -- setPendingCorrection's effect can fire the instant it's
          // called, so patching the image any later would race it -- and (b) a failed fetch here can
          // never skip the auto-correct decision that follows (mirrors this function's own outer
          // try/catch posture).
          try {
            const dataUrl = await fetchBlueprintDataUrl();
            patch(aid, (m) => ({ ...m, blueprintImage: dataUrl }));
          } catch {
            /* blueprint fetch is best-effort visibility; a failure must never break the turn or the
               validation/auto-correct flow below */
          }

          if (shouldAutoCorrect(report) && autoRoundRef.current < MAX_AUTO_ROUNDS && settings.apiKey) {
            // capture BEFORE incrementing: was THIS turn itself already a correction attempt? If so,
            // every op kind captured above is a fix that just failed (the self-check above still
            // found problems) -- pass them all to buildCorrectionMessage so the NEXT round's message
            // says so explicitly, instead of the model having no signal that repeating it is pointless
            // (see the thisTurn*Ops declarations' own comment for the confirmed live repros this
            // fixes). Pass NO_PRIOR_ATTEMPT when this turn was the ORIGINAL build, not a retry -- its
            // own first-pass ops are not a "prior fix attempt".
            const priorAttempt: PriorAttempt = autoRoundRef.current >= 1
              ? {
                  deltas: thisTurnDeltas,
                  featureOps: thisTurnFeatureOps,
                  instanceOps: thisTurnInstanceOps,
                  connectionOps: thisTurnConnectionOps,
                  couplingOps: thisTurnCouplingOps,
                }
              : NO_PRIOR_ATTEMPT;
            autoRoundRef.current += 1;
            const correction = buildCorrectionMessage(report, autoRoundRef.current, MAX_AUTO_ROUNDS, priorAttempt);
            setPendingCorrection(correction);   // the effect fires it once streaming settles, never re-entrantly
          }
        } catch {
          /* validation is best-effort; a failure must never break the chat turn */
        }
      }
    },
    [messages, streaming, settings, visionCapable, onApply, onUserMessage, onValidate,
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
            undoError={undoErrors[`${m.id}:delta`]}
            onHover={onHoverInstance}
            onUndo={async () => {
              // 2026-07-21 (foundations-audit H6): check the result instead of assuming success —
              // a reversal can be REJECTED/CONFLICTed (e.g. the node got HARD_LOCK'd since, or a
              // tightened invariant now rejects the old value). Mirrors the feature_op/instance_op
              // handlers just below, which already do this correctly.
              const result = await onUndo(m.outcomes!);
              if (result.ok) {
                setUndone((u) => ({ ...u, [m.id]: true }));
                setUndoErrors((s) => { const { [`${m.id}:delta`]: _drop, ...rest } = s; return rest; });
              } else {
                setUndoErrors((s) => ({ ...s, [`${m.id}:delta`]: result.reason || "undo failed" }));
              }
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
    if (m.regionOps && m.regionOps.length > 0) {
      sections.push({
        label: "Regions",
        content: (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {m.regionOps.map((op, i) => {
              const o = m.regionOpOutcomes?.[i];
              const ok = o?.status === "APPLIED";
              const color = o == null ? "#8b949e" : ok ? "#3fb950" : "#f85149";
              const label = op.op === "add_region"
                ? `${op.host_instance}: ${op.label} (${op.kind})`
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
    if (m.fitOps && m.fitOps.length > 0) {
      sections.push({
        label: "Fits",
        content: (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {m.fitOps.map((op, i) => {
              const o = m.fitOpOutcomes?.[i];
              const ok = o?.status === "APPLIED";
              const color = o == null ? "#8b949e" : ok ? "#3fb950" : "#f85149";
              const label = op.op === "fit_connector"
                ? `${op.connector_instance} <- ${op.host_instance}`
                : op.op === "resync_fit"
                ? `resync ${op.id}`
                : `unfit ${op.id}`;
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
    if (m.envelopeOps && m.envelopeOps.length > 0) {
      sections.push({
        label: "Housing",
        content: (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {m.envelopeOps.map((op, i) => {
              const o = m.envelopeOpOutcomes?.[i];
              const ok = o?.status === "APPLIED";
              const color = o == null ? "#8b949e" : ok ? "#3fb950" : "#f85149";
              const label = op.op === "wrap_group"
                ? `${op.housing_instance} wraps [${(op.member_instance_ids ?? []).join(", ")}]`
                : `${op.op} ${op.housing_instance}`;
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
    if (m.joinAnnotationOps && m.joinAnnotationOps.length > 0) {
      sections.push({
        label: "Joins",
        content: (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {m.joinAnnotationOps.map((op, i) => {
              const o = m.joinAnnotationOpOutcomes?.[i];
              const ok = o?.status === "APPLIED";
              const color = o == null ? "#8b949e" : ok ? "#3fb950" : "#f85149";
              const label = op.op === "add_join_annotation"
                ? `${op.connection_id}: ${op.method}`
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
        {m.researchFinding && <ResearchCard finding={m.researchFinding} />}
        <ChangesetCard sections={sections} />
        {m.blueprintImage && (
          <div style={{ border: "1px solid #30363d", borderRadius: 8, padding: "8px 10px", marginTop: 6, background: "#0d1117" }}>
            <div style={{ fontSize: 10, color: "#6e7681", marginBottom: 4 }}>
              Blueprint render — the same image the self-check judges (and, on an auto-correction,
              hands back to a vision-capable model so it can see its own placement)
            </div>
            <img
              src={m.blueprintImage}
              alt="Rendered blueprint of the current assembly"
              style={{ display: "block", width: "100%", maxWidth: 600, borderRadius: 6, border: "1px solid #30363d" }}
            />
          </div>
        )}
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
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            onClick={() => {
              const md = exportConversationToMarkdown(messages);
              const stamp = new Date().toISOString().replace(/[:.]/g, "-");
              triggerMarkdownDownload(`conversation-${stamp}.md`, md);
            }}
            disabled={messages.length === 0}
            title="Export this conversation as a .md file"
            style={{
              background: "none", border: "none", color: messages.length === 0 ? "#484f58" : "#8b949e",
              cursor: messages.length === 0 ? "default" : "pointer", fontSize: 16,
            }}
          >
            ⭳
          </button>
          <button
            onClick={async () => {
              setReportError(null);
              try {
                const md = await fetchDesignReport();
                const stamp = new Date().toISOString().replace(/[:.]/g, "-");
                triggerMarkdownDownload(`design-report-${stamp}.md`, md);
              } catch (err) {
                setReportError(String(err));
              }
            }}
            title="Export a design report (transmission, fasteners, keep-outs, coarse self-check — grounded in the current ledger, never a fabricated safety verdict)"
            style={{ background: "none", border: "none", color: "#8b949e", cursor: "pointer", fontSize: 16 }}
          >
            📄
          </button>
          <button onClick={onOpenSettings} title="LLM settings" style={{ background: "none", border: "none", color: "#8b949e", cursor: "pointer", fontSize: 16 }}>
            ⚙
          </button>
        </div>
      </div>
      {reportError && (
        <div style={{ fontSize: 11, color: "#f85149", padding: "4px 2px" }}>
          Design report failed: {reportError}
        </div>
      )}
      <MessageList messages={messages} renderExtras={renderExtras} onExample={send} />
      <Composer streaming={streaming} noKey={!settings.apiKey} onSend={send} onStop={stop} />
    </div>
  );
}
