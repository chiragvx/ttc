import { useEffect, useState } from "react";
import { activateInstance, addInstance, analyze, analyzeStatus, applyFeatureOp as postFeatureOp, applyConnectionOp as postConnectionOp, applyCouplingOp as postCouplingOp, applyInstanceOp as postInstanceOp, createFile, exportCheck, fetchTelemetry, getLedger, getManufacturingManifest, getParams, getRequirements, getSubsystems, listFiles, listInstances, openFile, optimize, optimizeStatus, removeInstance, runValidate, setGoal, signoff, type FileRow, type InstanceRow, type ParamSpec, type RequirementsData, type SubsystemInfo } from "./api";
import { AnalysisBar, type AnalysisState } from "./AnalysisBar";
import { OptimizeResult, type OptimizeResultData } from "./OptimizeResult";
import { Chat } from "./chat/Chat";
import { ValidationCard } from "./chat/ValidationCard";
import { EKGGraphView } from "./EKGGraphView";
import { ModelPanel } from "./ModelPanel";
import { Hud } from "./Hud";
import { SettingsModal } from "./SettingsModal";
import { Viewport } from "./Viewport";
import { loadSettings, type LlmSettings } from "./settings";
import { useCadSocket } from "./useCadSocket";
import { type ConnectionOp, type ConnectionOpOutcome, type CouplingOp, type CouplingOpOutcome, type DeltaOutcome, type FeatureOp, type FeatureOpOutcome, type InstanceOp, type InstanceOpOutcome, type LedgerGraphData, type ManufacturingManifest, type ParameterDelta, type ServerMessage, type ValidationResult } from "./types";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function App() {
  const { connected, telemetry, setTelemetry, lastReject, send } = useCadSocket();
  const [params, setParams] = useState<Record<string, number>>({});
  const [locked, setLocked] = useState<Record<string, boolean>>({});
  const [specs, setSpecs] = useState<ParamSpec[]>([]);
  // live invariant-valid slider clamps by node (2026-07-19) — seeded from /params, refreshed on every
  // WS mutation response so a slider can never be dragged into a CONFLICT (see sliderRange.ts)
  const [validRanges, setValidRanges] = useState<Record<string, { min: number; max: number }>>({});
  const [subsystems, setSubsystems] = useState<SubsystemInfo[]>([]);
  const [active, setActive] = useState<string | null>(null);  // null = empty file, no part yet
  const [instances, setInstances] = useState<InstanceRow[]>([]);
  const [files, setFiles] = useState<FileRow[]>([]);
  const [showFileMenu, setShowFileMenu] = useState(false);
  const [meshKey, setMeshKey] = useState(0);
  const [showManualPicker, setShowManualPicker] = useState(false);
  const [hoveredInstanceId, setHoveredInstanceId] = useState<string | null>(null);
  const [settings, setSettings] = useState<LlmSettings>(() => loadSettings());
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [analysis, setAnalysis] = useState<AnalysisState>({
    status: "idle", fs: null, solverSeconds: null, exportStatus: "EXPORT_BLOCKED",
  });
  const [optimizeResult, setOptimizeResult] = useState<OptimizeResultData | null>(null);
  const [requirements, setRequirements] = useState<RequirementsData | null>(null);
  // Phase 6 (manufacturability outputs): read-only make-manifest — material/process per part plus
  // the assembly steps derived from the connection graph. Fetched/refreshed symmetrically with
  // `requirements` above — same triggers, no separate refresh path invented.
  const [manufacturingManifest, setManufacturingManifest] = useState<ManufacturingManifest | null>(null);
  // View-mode tabs (2026-07-19): pure UI navigation over the SAME live model — never a gate on the
  // chat/AI path (see packages/agents/CLAUDE.md's auto-apply policy). Defaults to "3d" so existing
  // behavior is unaffected for anyone not using the new tabs.
  const [viewMode, setViewMode] = useState<"graph" | "3d" | "validation">("3d");
  const [ledgerGraph, setLedgerGraph] = useState<LedgerGraphData | null>(null);
  // On-demand self-check for the Validation tab — distinct from Chat.tsx's per-message `validation`
  // (ChatMessage.validation), which runs automatically after a turn changes geometry. This is the
  // same runValidate() call, just triggered by hand from the tab instead of from a chat turn.
  const [validationResult, setValidationResult] = useState<ValidationResult | null>(null);
  const [validationRunning, setValidationRunning] = useState(false);

  const refreshRequirements = async () => {
    try { setRequirements(await getRequirements()); } catch { /* ignore */ }
  };
  const refreshManufacturingManifest = async () => {
    try { setManufacturingManifest(await getManufacturingManifest()); } catch { /* ignore */ }
  };
  // Refreshed from the SAME sites as refreshManufacturingManifest/refreshRequirements above
  // (onGeometryChanged, runAnalyze, runOptimize, loadProject) so the graph view never goes stale
  // after a chat turn changes the design while a different tab happens to be showing — plus once
  // when the user switches into "graph" mode (see the effect below), so it's fresh on first view too.
  const refreshLedgerGraph = async () => {
    try { setLedgerGraph(await getLedger()); } catch { /* ignore */ }
  };
  const runStandaloneValidate = async () => {
    setValidationRunning(true);
    try { setValidationResult(await runValidate("", settings.apiKey)); }
    catch { /* ignore */ }
    finally { setValidationRunning(false); }
  };
  const applyGoal = async (goal: string) => {
    try { setRequirements(await setGoal(goal)); } catch { /* ignore */ }
  };
  const refreshFiles = async () => {
    try { setFiles((await listFiles()).files); } catch { /* ignore */ }
  };

  // load the ACTIVE INSTANCE's subsystem, its sliders (from /params), the part-type list, and the
  // full instance tree (for the outliner); refresh geometry for whichever instance is now active.
  // Returns whether it succeeded, so the initial-mount retry loop below knows whether to keep trying.
  const loadProject = async (): Promise<boolean> => {
    try {
      const [p, s, inst] = await Promise.all([getParams(), getSubsystems(), listInstances()]);
      setSpecs(p.params);
      setActive(p.subsystem);
      setSubsystems(s.available);
      setInstances(inst.instances);
      const vals: Record<string, number> = {};
      const lk: Record<string, boolean> = {};
      const vr: Record<string, { min: number; max: number }> = {};
      for (const sp of p.params) {
        vals[sp.node] = sp.value; lk[sp.node] = sp.locked;
        if (sp.valid_min != null && sp.valid_max != null) vr[sp.node] = { min: sp.valid_min, max: sp.valid_max };
      }
      setParams(vals);
      setLocked(lk);
      setValidRanges(vr);
      setMeshKey((k) => k + 1);
      const e = await exportCheck();
      setAnalysis((a) => ({ ...a, exportStatus: e.status }));
      void refreshRequirements();
      void refreshManufacturingManifest();
      void refreshLedgerGraph();
      void refreshFiles();
      // adding/removing a part is a REST call, not a WS mutation — the socket never sees it, so
      // Mass/CG/Print/Cost would otherwise sit on stale (or "—") numbers until the next slider
      // touch. Refresh explicitly every time the project view reloads.
      fetchTelemetry().then(setTelemetry).catch(() => {});
      return true;
    } catch (err) {
      console.error("loadProject failed:", err);
      return false;
    }
  };

  // Files (2026-07-04): a session can hold several independent design files (think browser tabs) —
  // replaces the old single-project "New Project" reset entirely. "Start completely over" is just
  // opening a new file; the one you had is still there to switch back to.
  const handleNewFile = async () => {
    await createFile();
    setOptimizeResult(null);
    setAnalysis({ status: "idle", fs: null, solverSeconds: null, exportStatus: "EXPORT_BLOCKED" });
    await loadProject();
  };
  const handleOpenFile = async (id: string) => {
    const r = await openFile(id);
    if (r.ok) {
      setOptimizeResult(null);
      setAnalysis({ status: "idle", fs: null, solverSeconds: null, exportStatus: "EXPORT_BLOCKED" });
      await loadProject();
    }
  };

  // Item 3: the outliner — select/add/remove an INSTANCE within the current project (independent of
  // switching the whole project's part type above). Selecting/adding/removing changes which part
  // /params, /mesh, /export target, so each reloads the full project view.
  const selectInstance = async (id: string) => {
    const r = await activateInstance(id);
    if (r.ok) await loadProject();
  };
  const addPart = async (subsystemType: string) => {
    const r = await addInstance(subsystemType);
    if (r.ok) {
      setOptimizeResult(null);
      setAnalysis({ status: "idle", fs: null, solverSeconds: null, exportStatus: "EXPORT_BLOCKED" });
      await loadProject();
    }
  };
  const removePart = async (id: string) => {
    const r = await removeInstance(id);
    if (r.ok) await loadProject();
  };

  // Retry the initial load — the backend may still be starting (dev-server race) or briefly down.
  // Without this, one failed fetch leaves the app stuck forever with subsystems=[] and no visible
  // error (every OTHER call site treats a failure as a silent no-op), which shows up as the chat's
  // "part isn't available" card listing nothing even once the backend is healthy again.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      for (let attempt = 0; !cancelled && attempt < 8; attempt++) {
        if (await loadProject()) return;
        await sleep(1000 * Math.min(attempt + 1, 5)); // backoff, capped at 5s
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Load the graph once when the user switches INTO "graph" mode — the other refresh sites below
  // keep it fresh once it's been fetched the first time; this covers the tab's first-ever view.
  useEffect(() => {
    if (viewMode === "graph") void refreshLedgerGraph();
  }, [viewMode]);

  // a geometry change invalidates the last analysis (resolver returns "unknown" -> export blocked);
  // it also re-grounds the goal compliance (FS back to unknown, mass/time recomputed)
  const onGeometryChanged = async () => {
    try {
      const e = await exportCheck();
      setAnalysis((a) => ({ ...a, exportStatus: e.status, status: a.status === "done" ? "stale" : a.status }));
      void refreshRequirements();
      void refreshManufacturingManifest();
      void refreshLedgerGraph();
    } catch {
      /* ignore */
    }
  };

  // every parameter change — from a slider OR the chat — goes through the rules-validated WS path.
  // `refresh=false` (used ONLY by applyDeltas/undo's own multi-delta loops below) skips the
  // per-call viewport/geometry refresh — see those functions' own comments for why: bumping meshKey
  // once per delta in a multi-delta batch queues up one expensive /mesh tessellation per delta (the
  // 200ms debounce in Viewport.tsx's Part effect only cancels the REACT STATE UPDATE for a stale
  // fetch, not the already-dispatched server-side request/computation itself — a real, confirmed
  // "large lofted body, multi-delta chat proposal" repro left the viewport showing nothing for tens
  // of seconds while several overlapping multi-second tessellations piled up server-side). Exactly
  // the same bug class refreshAfterOps below was already built to fix for instance_ops/feature_ops
  // batches — this extends that same "refresh once per batch, not once per item" fix to deltas.
  // The one string-valued target_node (packages/ledger/nodes.py::MATERIAL) — never belongs in the
  // numeric `params` slider-state dict below (no material dropdown/slider exists in this UI today;
  // ManufacturingCard reads it straight from the ledger instead), so setParams must skip it rather
  // than stuff a string into a Record<string, number> every OTHER component assumes is numeric.
  const MATERIAL_NODE = "domains.structure.material_profile";

  const mutate = async (
    node: string, value: number | string, lock?: string | null, refresh: boolean = true,
  ): Promise<ServerMessage> => {
    const resp = await send({ target_node: node, requested_value: value, set_lock: lock ?? null });
    if (resp.event_type === "PARAMETER_CASCADE_UPDATE") {
      if (node !== MATERIAL_NODE) {
        setParams((p) => {
          const next = { ...p, [node]: resp.mutations_applied[0].value as number };
          // a cascade may have moved a param OTHER than the one directly edited — reflect it in the
          // sliders immediately, don't wait for the next full reload to show the real ledger state
          for (const c of resp.cascades_applied) next[c.node] = c.value;
          return next;
        });
      }
      // refresh every slider's valid clamp — a change to one param can shift another's valid range
      // (e.g. raising span_mm widens blend_taper_mm's valid max), so all update together, live
      if (resp.valid_ranges && resp.valid_ranges.length) {
        setValidRanges((vr) => {
          const next = { ...vr };
          for (const r of resp.valid_ranges!) next[r.node] = { min: r.valid_min, max: r.valid_max };
          return next;
        });
      }
      if (refresh) {
        setMeshKey((k) => k + 1);
        void onGeometryChanged();
      }
    }
    return resp;
  };

  // Refreshes the viewport/geometry-derived state ONCE, not once per delta in the loops below — see
  // mutate()'s own comment for the confirmed repro this fixes.
  const applyDeltas = async (deltas: ParameterDelta[]): Promise<DeltaOutcome[]> => {
    const out: DeltaOutcome[] = [];
    for (const d of deltas) {
      try {
        const resp = await mutate(d.target_node, d.requested_value, d.set_lock ?? null, false);
        if (resp.event_type === "PARAMETER_CASCADE_UPDATE") {
          const m = resp.mutations_applied[0];
          out.push({ node: d.target_node, requested: d.requested_value, applied: m.value, oldValue: m.old_value ?? null, status: m.status as DeltaOutcome["status"], cascades: resp.cascades_applied });
        } else {
          out.push({ node: d.target_node, requested: d.requested_value, applied: null, oldValue: null, status: resp.status as DeltaOutcome["status"], reason: resp.reason });
        }
      } catch (e) {
        out.push({ node: d.target_node, requested: d.requested_value, applied: null, oldValue: null, status: "REJECTED", reason: String(e) });
      }
    }
    if (deltas.length) {
      setMeshKey((k) => k + 1);
      void onGeometryChanged();
    }
    return out;
  };

  const undo = async (outcomes: DeltaOutcome[]) => {
    let touched = false;
    for (const o of outcomes) {
      if (o.oldValue != null) {
        await mutate(o.node, o.oldValue, undefined, false);
        touched = true;
      }
    }
    if (touched) {
      setMeshKey((k) => k + 1);
      void onGeometryChanged();
    }
  };

  // human accepts one AI-proposed hole/pocket/slot cut -> POST /feature_ops (rules-validated, same
  // "propose then explicit accept" boundary as deltas' WS path). Does NOT refresh anything itself —
  // a chat turn can carry dozens of these (a detailed multi-part spec easily produces 20-30 ops in
  // one proposal); refreshing per-op turned a few seconds of real work into a multi-minute stall
  // with the UI showing nothing the whole time (see refreshAfterOps below). The caller refreshes
  // ONCE after the whole batch it's driving is done.
  const applyFeatureOp = async (op: FeatureOp): Promise<FeatureOpOutcome> => {
    try {
      const resp = await postFeatureOp(op);
      return {
        op, status: resp.status, instanceId: resp.instance_id, feature: resp.feature, reason: resp.message,
      };
    } catch (e) {
      return { op, status: "REJECTED", instanceId: op.instance_id, feature: null, reason: String(e) };
    }
  };

  // human accepts one AI-proposed add/remove/move-instance op -> POST /instance_ops (same "propose
  // then explicit accept" boundary as feature_ops above). Same reasoning as applyFeatureOp — no
  // refresh here, see refreshAfterOps.
  const applyInstanceOp = async (op: InstanceOp): Promise<InstanceOpOutcome> => {
    try {
      const resp = await postInstanceOp(op);
      return {
        op, status: resp.status, instanceId: resp.instance_id,
        subsystemType: resp.instance?.subsystem_type ?? null, instance: resp.instance,
        previousInstance: resp.previous_instance, reason: resp.message,
      };
    } catch (e) {
      return { op, status: "REJECTED", instanceId: op.instance_id ?? null, subsystemType: null, reason: String(e) };
    }
  };

  // Phase 1b: apply a typed interface mate. Like applyInstanceOp, does NOT refresh itself — the
  // proposal loop calls onOpsApplied once for the batch.
  const applyConnectionOp = async (op: ConnectionOp): Promise<ConnectionOpOutcome> => {
    try {
      const resp = await postConnectionOp(op);
      return { op, status: resp.status, connectionId: resp.connection_id, message: resp.message };
    } catch (e) {
      return { op, status: "REJECTED", connectionId: op.id ?? null, message: String(e) };
    }
  };

  // Phase 2b: apply a load coupling (a part's load derived from another part's condition). Like
  // applyConnectionOp, does NOT refresh itself — the proposal loop calls onOpsApplied once for the
  // batch.
  const applyCouplingOp = async (op: CouplingOp): Promise<CouplingOpOutcome> => {
    try {
      const resp = await postCouplingOp(op);
      return { op, status: resp.status, couplingId: resp.coupling_id, message: resp.message };
    } catch (e) {
      return { op, status: "REJECTED", couplingId: op.id ?? null, message: String(e) };
    }
  };

  // Called ONCE after a whole batch of feature_ops/instance_ops has finished applying (a full chat
  // proposal, or a single manual Undo click) — reloads the outliner/params/viewport/telemetry a
  // single time instead of once per op. 2026-07-04: a 25-part proposal was doing a full project
  // reload (6-7 requests) after EVERY successfully-applied op, sequentially — for a large batch that
  // turned into 100+ HTTP round-trips and over a minute with zero visible progress, indistinguishable
  // from a hang. See tests/acceptance and the live "build the full cubesat" repro that found this.
  const refreshAfterOps = async () => {
    setOptimizeResult(null);
    setAnalysis({ status: "idle", fs: null, solverSeconds: null, exportStatus: "EXPORT_BLOCKED" });
    await loadProject();
  };

  // Undo for an AI-proposed feature op. No literal undo exists (the event log doesn't snapshot
  // pre-change state independently — see packages/ledger/events.py), so this reverses by issuing
  // the opposite op: remove what was just added, or re-add what was removed (a fresh id, same
  // kind/shape/dims/position — geometrically equivalent, not the same CutFeature). Only offered for
  // add_feature/remove_feature outcomes (see FeatureOpCard) — update_feature has no prior state to
  // restore from, so it isn't undoable.
  const undoFeatureOp = async (outcome: FeatureOpOutcome): Promise<FeatureOpOutcome> => {
    if (outcome.op.op === "remove_feature") {
      const f = outcome.feature!;
      return applyFeatureOp({
        op: "add_feature", instance_id: outcome.instanceId, kind: f.kind, shape: f.shape,
        dia_mm: f.dia_mm, length_mm: f.length_mm, width_mm: f.width_mm, depth_mm: f.depth_mm,
        x_mm: f.x_mm, y_mm: f.y_mm,
      });
    }
    return applyFeatureOp({ op: "remove_feature", instance_id: outcome.instanceId, feature_id: outcome.feature?.id });
  };

  // Same idea for instance ops. add/remove restore subsystem_type + position only — InstanceOp has
  // no way to set a custom param on add_instance, so a removed instance's slider edits aren't
  // recoverable; this is a practical re-add, not a literal undo (see InstanceSnapshot in types.ts).
  // move_instance's Undo IS exact, though: `previousInstance` (2026-07-05) carries the instance's
  // full pre-move transform (position + rotation), so replaying it as a fresh move_instance restores
  // the identical prior pose.
  const undoInstanceOp = async (outcome: InstanceOpOutcome): Promise<InstanceOpOutcome> => {
    if (outcome.op.op === "remove_instance") {
      const snap = outcome.instance;
      return applyInstanceOp({
        op: "add_instance", subsystem_type: snap?.subsystem_type ?? outcome.subsystemType ?? undefined,
        parent_id: snap?.parent_id ?? undefined, x_mm: snap?.transform?.x_mm, y_mm: snap?.transform?.y_mm,
        z_mm: snap?.transform?.z_mm,
      });
    }
    if (outcome.op.op === "move_instance") {
      const prev = outcome.previousInstance;
      // move_instance's wire contract requires x_mm/y_mm/z_mm ALL THREE TOGETHER — there is no
      // "clear back to auto-layout" op. If the instance had never been explicitly positioned before
      // this move (prev.transform === null, i.e. it was living purely off auto-layout), or the
      // outcome simply carries no previousInstance at all (defensive — should only happen on a
      // REJECTED move, which the caller already excludes from offering Undo for), there is no
      // numeric pose to replay and no way to express "unset" through this endpoint. Rather than
      // guess — e.g. defaulting to 0,0,0, which IS a real, arbitrary position, not "no position" —
      // skip the real call and surface a clear, honest Undo failure instead.
      if (!prev || !prev.transform) {
        return {
          op: outcome.op, status: "REJECTED", instanceId: outcome.instanceId, subsystemType: null,
          reason: "no prior explicit position recorded (part was on auto-layout) — cannot undo the move",
        };
      }
      const t = prev.transform;
      return applyInstanceOp({
        op: "move_instance", instance_id: outcome.instanceId ?? undefined,
        x_mm: t.x_mm, y_mm: t.y_mm, z_mm: t.z_mm, rx_deg: t.rx_deg, ry_deg: t.ry_deg, rz_deg: t.rz_deg,
      });
    }
    return applyInstanceOp({ op: "remove_instance", instance_id: outcome.instanceId ?? undefined });
  };

  const runAnalyze = async () => {
    setAnalysis((a) => ({ ...a, status: "running", errorMessage: null }));
    try {
      // no loadN passed -> the backend resolves it (whatever the stated goal demands, else its own
      // default) and echoes back the resolved value as `load_n`; every poll below must ask about that
      // SAME case (see analyzeStatus's own comment), not silently re-send a hardcoded constant.
      const r = await analyze();
      if (r.status === "error") {
        setAnalysis((a) => ({ ...a, status: "error", errorMessage: r.message ?? null }));
        return;
      }
      const loadN: number = r.load_n;
      let verdict = r.verdict ?? null;
      // job_status/job_message (2026-07-15) let a durably-recorded worker crash stop this loop
      // immediately instead of silently burning the full 90s budget before giving up unexplained.
      for (let i = 0; r.status === "queued" && !verdict && i < 60; i++) {
        await sleep(1500);
        const s = await analyzeStatus(loadN);
        verdict = s.current;
        if (s.job_status === "failed") {
          setAnalysis((a) => ({ ...a, status: "error", errorMessage: s.job_message ?? "analysis failed" }));
          return;
        }
      }
      const e = await exportCheck();
      setAnalysis({
        status: "done", fs: verdict?.factor_of_safety ?? null,
        solverSeconds: verdict?.solver_seconds ?? null, exportStatus: e.status,
      });
      void refreshRequirements(); // FS is now grounded -> the compliance readout can go green
      void refreshManufacturingManifest();
      void refreshLedgerGraph();
    } catch {
      setAnalysis((a) => ({ ...a, status: "error" }));
    }
  };

  const runOptimize = async () => {
    setAnalysis((a) => ({ ...a, status: "optimizing" }));
    try {
      // no loadN passed -> same goal-resolution as runAnalyze; /optimize/status needs no load_n since
      // it just reads back whatever result was stored for this project, not a specific (material,
      // load_n) case.
      const r = await optimize();
      if (r.status === "unsupported") {
        // the active subsystem has no fea_eligible thickness param to sweep — not a failure, just
        // not offered for this part type (e.g. a cylindrical/rotational part, or a compound)
        setAnalysis((a) => ({ ...a, status: "error" }));
        return;
      }
      let result = r.status === "done" ? r : null; // inline (dev) returns the result directly
      // job_status/job_message (2026-07-15) let a durably-recorded worker crash stop this loop
      // immediately instead of silently burning the full 240s budget before giving up unexplained.
      for (let i = 0; r.status === "queued" && !result && i < 120; i++) {
        await sleep(2000); // durable (compose) path: the worker runs the sweep, poll for it
        const s = await optimizeStatus();
        if (s.result) result = s.result;
        if (s.job_status === "failed") {
          setOptimizeResult({ variants: [], bestValue: null, bestMass: null, paramName: null });
          setAnalysis((a) => ({ ...a, status: "error", errorMessage: s.job_message ?? "optimize failed" }));
          return;
        }
      }
      if (!result || result.best_value == null) {
        setOptimizeResult({ variants: result?.variants ?? [], bestValue: null, bestMass: null, paramName: result?.param_name ?? null });
        setAnalysis((a) => ({ ...a, status: "error" }));
        return;
      }
      // apply through the rules path -> ledger + viewport follow. The endpoint always reports the
      // exact dotted path for whichever instance it swept — never a hardcoded fallback constant.
      await mutate(result.target_node, result.best_value);
      const best = result.variants.find((v: { value: number }) => v.value === result.best_value);
      const e = await exportCheck();
      setOptimizeResult({ variants: result.variants, bestValue: result.best_value, bestMass: result.best_mass_g, paramName: result.param_name ?? null });
      setAnalysis({ status: "done", fs: best?.fs ?? null, solverSeconds: null, exportStatus: e.status });
      void refreshRequirements();
      void refreshManufacturingManifest();
      void refreshLedgerGraph();
    } catch {
      setAnalysis((a) => ({ ...a, status: "error" }));
    }
  };

  const signAndExport = async () => {
    const s = await signoff();
    if (!s.ok) {
      setAnalysis((a) => ({ ...a, status: "error", errorMessage: s.message ?? "sign-off blocked" }));
      return;
    }
    const e = await exportCheck();
    setAnalysis((a) => ({ ...a, exportStatus: e.status }));
    if (e.status === "EXPORT_ELIGIBLE") window.open("/export/step", "_blank");
  };

  return (
    <div style={{ display: "grid", gridTemplateRows: "auto 1fr auto", height: "100%" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 16px", borderBottom: "1px solid #30363d", background: "#161b22" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <strong>Grounded Text-to-CAD</strong>
          {/* File switcher (2026-07-04) — replaces the old single-project "New Project" reset.
              Files are independent design sessions (think browser tabs); "start completely over"
              is just opening a new one, never a destructive action on the one you had. */}
          <span style={{ position: "relative" }}>
            <button
              onClick={() => setShowFileMenu((v) => !v)}
              title="Switch files, or start a new one"
              style={{ background: "none", border: "1px solid #30363d", borderRadius: 4, color: "#c9d1d9",
                       cursor: "pointer", fontSize: 12, padding: "2px 8px" }}
            >
              🗎 {files.find((f) => f.is_active)?.name ?? "…"} ▾
            </button>
            {showFileMenu && (
              <div style={{ position: "absolute", top: "100%", left: 0, marginTop: 4, background: "#161b22",
                            border: "1px solid #30363d", borderRadius: 6, zIndex: 10, minWidth: 170,
                            boxShadow: "0 4px 12px rgba(0,0,0,0.4)" }}>
                {files.map((f) => (
                  <div key={f.id}
                       onClick={() => { setShowFileMenu(false); if (!f.is_active) void handleOpenFile(f.id); }}
                       style={{ padding: "6px 10px", cursor: "pointer", fontSize: 12, whiteSpace: "nowrap",
                                background: f.is_active ? "#1f6feb22" : "transparent",
                                color: f.is_active ? "#c9d1d9" : "#8b949e" }}>
                    {f.name} <span style={{ color: "#6e7681", fontSize: 10 }}>
                      ({f.part_count} part{f.part_count === 1 ? "" : "s"})
                    </span>
                  </div>
                ))}
                <div onClick={() => { setShowFileMenu(false); void handleNewFile(); }}
                     style={{ padding: "6px 10px", cursor: "pointer", fontSize: 12, color: "#8b949e",
                              borderTop: "1px solid #30363d" }}>
                  ＋ New File
                </div>
              </div>
            )}
          </span>
          {/* Status pill — an empty file to start (2026-07-04): the copilot adds parts from your
              intent via instance_ops. The chevron reveals a manual "add a part" picker (also shown
              automatically when no LLM key is configured, since that's otherwise the only way in). */}
          <span style={{ fontSize: 12, color: "#8b949e", display: "inline-flex", alignItems: "center", gap: 6 }}>
            Part:&nbsp;<b style={{ color: "#c9d1d9" }}>{active ?? "— empty —"}</b>
            <button
              onClick={() => setShowManualPicker((v) => !v)}
              title="Manually add a part — normally the copilot adds one from your request"
              style={{ background: "none", border: "1px solid #30363d", borderRadius: 4, color: "#8b949e",
                       cursor: "pointer", fontSize: 10, padding: "1px 6px" }}
            >
              {showManualPicker ? "✕" : "⇅"}
            </button>
            {(showManualPicker || !settings.apiKey) && (
              <select value="" onChange={(e) => { if (e.target.value) void addPart(e.target.value); }}
                      style={{ background: "#0d1117", color: "#c9d1d9", border: "1px solid #30363d",
                               borderRadius: 6, padding: "2px 6px", maxWidth: 180 }}>
                <option value="">{active ? "+ add part…" : "— choose a part —"}</option>
                {subsystems.map((s) => (<option key={s.name} value={s.name}>{s.name}</option>))}
              </select>
            )}
          </span>
          <span style={{ fontSize: 11, color: "#6e7681", fontStyle: "italic" }}>
            (tell the copilot what part you want)
          </span>
        </div>
        <span style={{ fontSize: 12, color: connected ? "#3fb950" : "#f85149" }}>
          {connected ? "● connected" : "● offline"} · {settings.apiKey ? "DeepSeek" : "no LLM"}
        </span>
      </header>

      <div style={{ display: "grid", gridTemplateColumns: "380px 1fr", minHeight: 0 }}>
        {/* Chat-only sidebar (2026-07-04 redesign): the parts outliner + params + goal all describe
            the CURRENT MODEL, not the conversation — they moved to a floating panel over the
            viewport (ModelPanel) so a design with many parts no longer squeezes the chat down to a
            sliver. This column is now always 100% chat. */}
        <aside style={{ padding: 14, borderRight: "1px solid #30363d", minHeight: 0, display: "flex", flexDirection: "column" }}>
          <div style={{ flex: 1, minHeight: 0 }}>
            <Chat settings={settings} onApply={applyDeltas} onUndo={undo} onApplyFeatureOp={applyFeatureOp}
                  onApplyInstanceOp={applyInstanceOp} onUndoFeatureOp={undoFeatureOp} onUndoInstanceOp={undoInstanceOp}
                  onOpsApplied={refreshAfterOps}
                  onApplyConnectionOp={applyConnectionOp}
                  onApplyCouplingOp={applyCouplingOp}
                  onValidate={(intent) => runValidate(intent, settings.apiKey)}
                  onUserMessage={applyGoal} onHoverInstance={setHoveredInstanceId}
                  onOpenSettings={() => setSettingsOpen(true)} />
          </div>
        </aside>
        <main style={{ position: "relative", minHeight: 0 }}>
          {/* View-mode tab strip (2026-07-19) — pure UI navigation between the 3D viewport, the EKG
              topology graph, and an on-demand self-check; never touches chat/apply/undo logic. Styled
              to match ModelPanel's own floating-panel look (border/background/radius/blur below). */}
          <div style={tabStrip}>
            {(["3d", "graph", "validation"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setViewMode(m)}
                style={{ ...tabBtn, ...(viewMode === m ? tabBtnActive : {}) }}
              >
                {m === "3d" ? "3D" : m === "graph" ? "Graph" : "Validation"}
              </button>
            ))}
          </div>

          {/* kept MOUNTED across tab switches (CSS-hidden, not conditionally rendered) — Viewport and
              its inner Part component hold real local state (camera selection, autoRotate, the loaded
              mesh/features) that a conditional `viewMode === "3d" && <Viewport .../>` would tear down
              and rebuild from scratch on every round-trip through another tab, silently resetting the
              camera/selection and re-fetching /mesh + /mesh/features even though refreshKey hadn't
              actually changed (2026-07-19 review, MEDIUM).
              `position:absolute; inset:0` (NOT `display:contents`) — react-three-fiber's <Canvas> sizes
              itself to 100%/100% of its immediate parent; `display:contents` removes that parent from
              the box tree entirely, which is a known source of percentage-sizing/ResizeObserver edge
              cases across browsers. `visibility:hidden` (not `display:none`) hides it, keeps it mounted
              with a real, stable size at all times, and implicitly removes it from hit-testing —
              `pointerEvents:none` while hidden is belt-and-suspenders on top of that. */}
          <div style={{
            position: "absolute", inset: 0,
            visibility: viewMode === "3d" ? "visible" : "hidden",
            pointerEvents: viewMode === "3d" ? "auto" : "none",
          }}>
            <Viewport refreshKey={meshKey} hoveredInstanceId={hoveredInstanceId} instances={instances} />
          </div>
          {viewMode === "graph" && (
            // key={activeFileId} (2026-07-19 review, MEDIUM): EKGGraphView stays mounted across a file
            // switch (gated on viewMode alone, not the active file), and its drag-position cache is
            // keyed by bare instance id — but instance ids are minted per-file-locally
            // (packages/transport/app.py's "{subsystem_type}_{n}" counter checks only the CURRENT
            // file's own ledger), so two unrelated files' first bracket both mint "bracket_1". Without
            // this key, dragging a node in file A and then switching to file B would silently reuse
            // file A's leftover position for file B's same-named instance. A React `key` forces a full
            // remount (fresh position cache) whenever the active file actually changes.
            <EKGGraphView key={files.find((f) => f.is_active)?.id}
                          ledger={ledgerGraph} selectedInstanceId={active} onSelectInstance={selectInstance} />
          )}
          {viewMode === "validation" && (
            <div style={validationTabWrap}>
              {validationResult ? (
                <ValidationCard result={validationResult} />
              ) : (
                <div style={{ fontSize: 12, color: "#6e7681", fontStyle: "italic" }}>
                  {validationRunning ? "Running self-check…" : "No self-check run yet — click below to run one."}
                </div>
              )}
              <button onClick={() => void runStandaloneValidate()} disabled={validationRunning} style={reRunBtn}>
                {validationRunning ? "Checking…" : "Re-run self-check"}
              </button>
            </div>
          )}

          <ModelPanel
            instances={instances}
            subsystems={subsystems}
            specs={specs}
            values={params}
            locked={locked}
            validRanges={validRanges}
            requirements={requirements}
            manufacturingManifest={manufacturingManifest}
            onSelect={selectInstance}
            onAdd={addPart}
            onRemove={removePart}
            onHover={setHoveredInstanceId}
            onOptimize={runOptimize}
            onChange={(node, v) => mutate(node, v)}
            onLock={(node, lock) => {
              setLocked((l) => ({ ...l, [node]: lock }));
              mutate(node, params[node], lock ? "HARD_LOCK" : "DYNAMIC");
            }}
          />
          {optimizeResult && <OptimizeResult result={optimizeResult} onClose={() => setOptimizeResult(null)} />}
        </main>
      </div>

      <div>
        <AnalysisBar state={analysis} onAnalyze={runAnalyze} onOptimize={runOptimize} onSignExport={signAndExport} />
        <Hud telemetry={telemetry} reject={lastReject} />
      </div>

      {settingsOpen && <SettingsModal value={settings} onChange={setSettings} onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}

// View-mode tab strip + Validation-tab styling — mirrors ModelPanel.tsx's own floating-panel look
// (border #30363d, background rgba(22,27,34,0.92), 10px radius, blur) so the new control reads as
// part of the same visual system rather than a bolted-on piece.
//
// top: 60 (NOT 16) — 2026-07-19 live bug: this used to sit at top:16/left:16, the EXACT same spot as
// Viewport.tsx's own toolbar (Fit/Rotate/Blueprint — also top:16/left:16/zIndex:5), so the two
// absolutely-positioned controls rendered directly on top of each other. ModelPanel occupies the
// right side (top:16/right:16/bottom:16), so the tab strip moves DOWN instead, stacking below the
// viewport toolbar rather than colliding with either existing floating panel.
const tabStrip: React.CSSProperties = {
  position: "absolute", top: 60, left: 16, zIndex: 5, display: "flex", gap: 2, padding: 4,
  background: "rgba(22,27,34,0.92)", border: "1px solid #30363d", borderRadius: 10,
  boxShadow: "0 8px 24px rgba(0,0,0,0.45)", backdropFilter: "blur(6px)",
};
const tabBtn: React.CSSProperties = {
  background: "none", border: "none", borderRadius: 6, color: "#8b949e",
  cursor: "pointer", fontSize: 12, padding: "4px 10px",
};
const tabBtnActive: React.CSSProperties = { background: "#1f6feb22", color: "#c9d1d9" };
const validationTabWrap: React.CSSProperties = {
  position: "absolute", inset: 0, paddingTop: 108, paddingLeft: 24, paddingRight: 24, paddingBottom: 24,
  overflowY: "auto", display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 12,
  background: "#0d1117",
};
const reRunBtn: React.CSSProperties = {
  background: "none", border: "1px solid #30363d", borderRadius: 6, color: "#c9d1d9",
  cursor: "pointer", fontSize: 12, padding: "4px 10px",
};
