import { useEffect, useState } from "react";
import { analyze, analyzeStatus, exportCheck, signoff } from "./api";
import { AnalysisBar, type AnalysisState } from "./AnalysisBar";
import { Chat } from "./chat/Chat";
import { FloatingControls } from "./FloatingControls";
import { Hud } from "./Hud";
import { SettingsModal } from "./SettingsModal";
import { Viewport } from "./Viewport";
import { loadSettings, type LlmSettings } from "./settings";
import { useCadSocket } from "./useCadSocket";
import { RIB, SKIN, type DeltaOutcome, type ParameterDelta, type ServerMessage } from "./types";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function App() {
  const { connected, telemetry, lastReject, send } = useCadSocket();
  const [params, setParams] = useState<Record<string, number>>({ [SKIN]: 2, [RIB]: 20 });
  const [locked, setLocked] = useState<Record<string, boolean>>({});
  const [settings, setSettings] = useState<LlmSettings>(() => loadSettings());
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [analysis, setAnalysis] = useState<AnalysisState>({
    status: "idle", fs: null, solverSeconds: null, exportStatus: "EXPORT_BLOCKED",
  });

  useEffect(() => {
    exportCheck().then((e) => setAnalysis((a) => ({ ...a, exportStatus: e.status }))).catch(() => {});
  }, []);

  // a geometry change invalidates the last analysis (resolver returns "unknown" -> export blocked)
  const onGeometryChanged = async () => {
    try {
      const e = await exportCheck();
      setAnalysis((a) => ({ ...a, exportStatus: e.status, status: a.status === "done" ? "stale" : a.status }));
    } catch {
      /* ignore */
    }
  };

  // every parameter change — from a slider OR the chat — goes through the rules-validated WS path
  const mutate = async (node: string, value: number, lock?: string | null): Promise<ServerMessage> => {
    const resp = await send({ target_node: node, requested_value: value, set_lock: lock ?? null });
    if (resp.event_type === "PARAMETER_CASCADE_UPDATE") {
      setParams((p) => ({ ...p, [node]: resp.mutations_applied[0].value }));
      void onGeometryChanged();
    }
    return resp;
  };

  const applyDeltas = async (deltas: ParameterDelta[]): Promise<DeltaOutcome[]> => {
    const out: DeltaOutcome[] = [];
    for (const d of deltas) {
      try {
        const resp = await mutate(d.target_node, d.requested_value, d.set_lock ?? null);
        if (resp.event_type === "PARAMETER_CASCADE_UPDATE") {
          const m = resp.mutations_applied[0];
          out.push({ node: d.target_node, requested: d.requested_value, applied: m.value, oldValue: m.old_value ?? null, status: m.status as DeltaOutcome["status"] });
        } else {
          out.push({ node: d.target_node, requested: d.requested_value, applied: null, oldValue: null, status: resp.status as DeltaOutcome["status"], reason: resp.reason });
        }
      } catch (e) {
        out.push({ node: d.target_node, requested: d.requested_value, applied: null, oldValue: null, status: "REJECTED", reason: String(e) });
      }
    }
    return out;
  };

  const undo = async (outcomes: DeltaOutcome[]) => {
    for (const o of outcomes) {
      if (o.oldValue != null) await mutate(o.node, o.oldValue);
    }
  };

  const runAnalyze = async () => {
    setAnalysis((a) => ({ ...a, status: "running" }));
    try {
      const r = await analyze(40);
      if (r.status === "error") {
        setAnalysis((a) => ({ ...a, status: "error" }));
        return;
      }
      let verdict = r.verdict ?? null;
      for (let i = 0; r.status === "queued" && !verdict && i < 60; i++) {
        await sleep(1500);
        verdict = (await analyzeStatus()).current;
      }
      const e = await exportCheck();
      setAnalysis({
        status: "done", fs: verdict?.factor_of_safety ?? null,
        solverSeconds: verdict?.solver_seconds ?? null, exportStatus: e.status,
      });
    } catch {
      setAnalysis((a) => ({ ...a, status: "error" }));
    }
  };

  const signAndExport = async () => {
    await signoff();
    const e = await exportCheck();
    setAnalysis((a) => ({ ...a, exportStatus: e.status }));
    if (e.status === "EXPORT_ELIGIBLE") window.open("/export/step", "_blank");
  };

  return (
    <div style={{ display: "grid", gridTemplateRows: "auto 1fr auto", height: "100%" }}>
      <header style={{ display: "flex", justifyContent: "space-between", padding: "8px 16px", borderBottom: "1px solid #30363d", background: "#161b22" }}>
        <strong>Grounded Text-to-CAD</strong>
        <span style={{ fontSize: 12, color: connected ? "#3fb950" : "#f85149" }}>
          {connected ? "● connected" : "● offline"} · {settings.apiKey ? "DeepSeek" : "no LLM"}
        </span>
      </header>

      <div style={{ display: "grid", gridTemplateColumns: "380px 1fr", minHeight: 0 }}>
        <aside style={{ padding: 14, borderRight: "1px solid #30363d", minHeight: 0 }}>
          <Chat settings={settings} onApply={applyDeltas} onUndo={undo} onOpenSettings={() => setSettingsOpen(true)} />
        </aside>
        <main style={{ position: "relative", minHeight: 0 }}>
          <Viewport skinMm={params[SKIN]} />
          <FloatingControls
            value={params}
            locked={locked}
            onChange={(node, v) => mutate(node, v)}
            onLock={(node, lock) => {
              setLocked((l) => ({ ...l, [node]: lock }));
              mutate(node, params[node], lock ? "HARD_LOCK" : "DYNAMIC");
            }}
          />
        </main>
      </div>

      <div>
        <AnalysisBar state={analysis} onAnalyze={runAnalyze} onSignExport={signAndExport} />
        <Hud telemetry={telemetry} reject={lastReject} />
      </div>

      {settingsOpen && <SettingsModal value={settings} onChange={setSettings} onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}
