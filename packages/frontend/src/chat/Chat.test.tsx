import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Chat } from "./Chat";
import type {
  ChatContentPart,
  ChatEvent,
  ConnectionOpOutcome,
  CouplingOpOutcome,
  DeltaOutcome,
  EnvelopeOpOutcome,
  FeatureOpOutcome,
  FitOpOutcome,
  InstanceOpOutcome,
  JoinAnnotationOpOutcome,
  ParameterDelta,
  RegionOpOutcome,
  ValidationResult,
} from "../types";
import type { LlmSettings } from "../settings";

// Render-in-the-loop (2026-08-05) — this is the wiring R2 flagged as untested: the blueprint <img>
// block in Chat.tsx's renderExtras, and the isAuto/priorBlueprintImage/`i === messages.length`
// bookkeeping in send() that decides which correction turn's outgoing message gets the image
// attached. buildChatContent.ts's own multimodal-shape logic is already unit-tested in isolation
// (buildChatContent.test.ts) and exportConversation.ts's embed is covered in exportConversation.test.ts
// — this file is deliberately scoped to the stateful integration point neither of those touches: a
// real send() pass through the component, with streamChat/onApply/onValidate/fetchBlueprintDataUrl
// mocked at the seam, asserting on what actually reaches the DOM and what actually gets posted back
// out as the next turn's `content`.

vi.mock("../api", () => ({
  fetchBlueprintDataUrl: vi.fn(),
  fetchDesignReport: vi.fn(),
  fetchModelVisionCapable: vi.fn(),
  streamChat: vi.fn(),
}));

import { fetchBlueprintDataUrl, fetchModelVisionCapable, streamChat } from "../api";

const settings: LlmSettings = { apiKey: "test-key", model: "openai/gpt-5.6-luna", authToken: "", visionModel: "" };
const BLUEPRINT_URL = "data:image/png;base64,BLUEPRINTDATA";

function proposalEvent(deltas: ParameterDelta[] = []): ChatEvent {
  return {
    type: "proposal",
    deltas,
    feature_ops: [],
    instance_ops: [],
    connection_ops: [],
    coupling_ops: [],
    fit_ops: [],
    envelope_ops: [],
    join_annotation_ops: [],
    region_ops: [],
    scope_proposal: null,
    clarification: null,
    suggestions: [],
  };
}

function makeReport(overrides: Partial<ValidationResult> = {}): ValidationResult {
  return {
    ok: true,
    geometric: { ok: true, issues: [], summary: "" },
    structural: { ok: true, issues: [], summary: "" },
    visual: null,
    vision_enabled: false,
    vision_ran: false,
    ...overrides,
  };
}

// Triggers shouldAutoCorrect(report) === true (packages/frontend/src/chat/shouldAutoCorrect.ts fires
// unconditionally on a "connectivity" issue, regardless of severity).
const CORRECTABLE_REPORT = makeReport({
  ok: false,
  geometric: {
    ok: false,
    issues: [{ check: "connectivity", severity: "warning", message: "bracket_1 is disconnected", instances: ["bracket_1"] }],
    summary: "",
  },
});

const APPLIED_OUTCOME: DeltaOutcome[] = [
  { node: "root.thickness_mm", requested: 5, applied: 5, oldValue: 3, status: "APPLIED" },
];

function baseProps() {
  return {
    settings,
    onApply: vi.fn().mockResolvedValue(APPLIED_OUTCOME),
    onUndo: vi.fn().mockResolvedValue({ ok: true }),
    onApplyFeatureOp: vi.fn().mockResolvedValue({} as FeatureOpOutcome),
    onApplyInstanceOp: vi.fn().mockResolvedValue({} as InstanceOpOutcome),
    onApplyConnectionOp: vi.fn().mockResolvedValue({} as ConnectionOpOutcome),
    onApplyCouplingOp: vi.fn().mockResolvedValue({} as CouplingOpOutcome),
    onApplyFitOp: vi.fn().mockResolvedValue({} as FitOpOutcome),
    onApplyEnvelopeOp: vi.fn().mockResolvedValue({} as EnvelopeOpOutcome),
    onApplyJoinAnnotationOp: vi.fn().mockResolvedValue({} as JoinAnnotationOpOutcome),
    onApplyRegionOp: vi.fn().mockResolvedValue({} as RegionOpOutcome),
    onUndoFeatureOp: vi.fn().mockResolvedValue({} as FeatureOpOutcome),
    onUndoInstanceOp: vi.fn().mockResolvedValue({} as InstanceOpOutcome),
    onOpsApplied: vi.fn().mockResolvedValue(undefined),
    onValidate: vi.fn().mockResolvedValue(makeReport()),
    onOpenSettings: vi.fn(),
  };
}

function sendMessage(text: string) {
  const textarea = screen.getByPlaceholderText(/Ask or instruct/i);
  fireEvent.change(textarea, { target: { value: text } });
  fireEvent.click(screen.getByText("Send"));
}

beforeEach(() => {
  vi.mocked(streamChat).mockReset();
  vi.mocked(fetchBlueprintDataUrl).mockReset();
  vi.mocked(fetchModelVisionCapable).mockReset();
});

describe("Chat — render-in-the-loop blueprint visibility", () => {
  it("renders the self-check's blueprint image as an <img> once a geometry-changing turn's self-check completes", async () => {
    vi.mocked(fetchModelVisionCapable).mockResolvedValue(false);
    vi.mocked(fetchBlueprintDataUrl).mockResolvedValue(BLUEPRINT_URL);
    vi.mocked(streamChat).mockImplementation(async (_messages, _settings, onEvent) => {
      await onEvent(proposalEvent([{ target_node: "root.thickness_mm", requested_value: 5 }]));
      await onEvent({ type: "done" });
    });
    const onValidate = vi.fn().mockResolvedValue(makeReport()); // ok -- no auto-correction

    render(<Chat {...baseProps()} onValidate={onValidate} />);
    sendMessage("make it 5mm thick");

    const img = await screen.findByAltText("Rendered blueprint of the current assembly");
    expect(img).toHaveAttribute("src", BLUEPRINT_URL);
    expect(onValidate).toHaveBeenCalledWith("make it 5mm thick");
  });

  it("does not render a blueprint <img> for a turn whose self-check never ran (no geometry applied)", async () => {
    vi.mocked(fetchModelVisionCapable).mockResolvedValue(false);
    vi.mocked(fetchBlueprintDataUrl).mockResolvedValue(BLUEPRINT_URL);
    // no deltas/ops at all -- appliedGeometry stays false, onValidate/fetchBlueprintDataUrl never run
    vi.mocked(streamChat).mockImplementation(async (_messages, _settings, onEvent) => {
      await onEvent({ type: "token", text: "here's what I can change..." });
      await onEvent({ type: "done" });
    });
    const onValidate = vi.fn();

    render(<Chat {...baseProps()} onValidate={onValidate} />);
    sendMessage("what can I change?");

    await waitFor(() => expect(screen.getByText(/here's what I can change/)).toBeInTheDocument());
    expect(screen.queryByAltText("Rendered blueprint of the current assembly")).not.toBeInTheDocument();
    expect(onValidate).not.toHaveBeenCalled();
    expect(fetchBlueprintDataUrl).not.toHaveBeenCalled();
  });
});

describe("Chat — auto-correction turn image attachment", () => {
  it("attaches the blueprint image to the auto-correction turn's outgoing message, at the newly-added message's index, sourced from the immediately preceding assistant message", async () => {
    vi.mocked(fetchModelVisionCapable).mockResolvedValue(true);
    vi.mocked(fetchBlueprintDataUrl).mockResolvedValue(BLUEPRINT_URL);
    const onValidate = vi.fn().mockResolvedValue(CORRECTABLE_REPORT);

    let call = 0;
    vi.mocked(streamChat).mockImplementation(async (_messages, _settings, onEvent) => {
      call += 1;
      if (call === 1) {
        await onEvent(proposalEvent([{ target_node: "root.thickness_mm", requested_value: 5 }]));
      }
      // round 2 (the auto-correction call) proposes nothing further -- appliedGeometry stays false,
      // so no round 3 is queued and the test can assert on exactly one correction call.
      await onEvent({ type: "done" });
    });

    render(<Chat {...baseProps()} onValidate={onValidate} />);
    sendMessage("make it 5mm thick");

    await waitFor(() => expect(streamChat).toHaveBeenCalledTimes(2));

    const [correctionHistory] = vi.mocked(streamChat).mock.calls[1];
    // user1, assistant1 (the original turn), user2 (the auto-queued correction turn)
    expect(correctionHistory).toHaveLength(3);
    expect(typeof correctionHistory[0].content).toBe("string");
    expect(typeof correctionHistory[1].content).toBe("string");

    const correctionContent = correctionHistory[2].content;
    expect(Array.isArray(correctionContent)).toBe(true);
    const parts = correctionContent as ChatContentPart[];
    expect(parts.find((p) => p.type === "text")).toBeTruthy();
    const imagePart = parts.find((p) => p.type === "image_url");
    expect(imagePart?.image_url?.url).toBe(BLUEPRINT_URL);
  });

  it("does not attach any image to the correction turn when the configured model is not vision-capable", async () => {
    vi.mocked(fetchModelVisionCapable).mockResolvedValue(false);
    vi.mocked(fetchBlueprintDataUrl).mockResolvedValue(BLUEPRINT_URL);
    const onValidate = vi.fn().mockResolvedValue(CORRECTABLE_REPORT);

    let call = 0;
    vi.mocked(streamChat).mockImplementation(async (_messages, _settings, onEvent) => {
      call += 1;
      if (call === 1) {
        await onEvent(proposalEvent([{ target_node: "root.thickness_mm", requested_value: 5 }]));
      }
      await onEvent({ type: "done" });
    });

    render(<Chat {...baseProps()} onValidate={onValidate} />);
    sendMessage("make it 5mm thick");

    await waitFor(() => expect(streamChat).toHaveBeenCalledTimes(2));

    const [correctionHistory] = vi.mocked(streamChat).mock.calls[1];
    expect(correctionHistory).toHaveLength(3);
    expect(typeof correctionHistory[2].content).toBe("string");
  });

  it("does not attach the blueprint image to a NEW manual user turn, even though a prior assistant message carries one and the model is vision-capable", async () => {
    vi.mocked(fetchModelVisionCapable).mockResolvedValue(true);
    vi.mocked(fetchBlueprintDataUrl).mockResolvedValue(BLUEPRINT_URL);
    const onValidate = vi.fn().mockResolvedValue(makeReport()); // ok -- no auto-correction, so the
    // NEXT send() below is a genuine manual turn, not one queued by the correction effect.
    vi.mocked(streamChat).mockImplementation(async (_messages, _settings, onEvent) => {
      await onEvent(proposalEvent([{ target_node: "root.thickness_mm", requested_value: 5 }]));
      await onEvent({ type: "done" });
    });

    render(<Chat {...baseProps()} onValidate={onValidate} />);
    sendMessage("make it 5mm thick");
    // wait for round 1 to fully settle (including the blueprintImage patch) before sending the next
    // real message -- otherwise this would race the self-check instead of testing the isAuto gate.
    await screen.findByAltText("Rendered blueprint of the current assembly");

    sendMessage("now make it green");
    await waitFor(() => expect(streamChat).toHaveBeenCalledTimes(2));

    const [secondHistory] = vi.mocked(streamChat).mock.calls[1];
    expect(secondHistory).toHaveLength(3); // user1, assistant1 (with blueprintImage), user2
    expect(typeof secondHistory[2].content).toBe("string");
    expect(secondHistory[2].content).toContain("now make it green");
  });
});

describe("Chat — self-check re-run on a no-op turn (2026-08-05 root-cause #4)", () => {
  it("re-runs onValidate on a turn that applies zero ops when the prior turn's report was unresolved (ok: false)", async () => {
    vi.mocked(fetchModelVisionCapable).mockResolvedValue(false);
    vi.mocked(fetchBlueprintDataUrl).mockResolvedValue(BLUEPRINT_URL);
    const onValidate = vi.fn().mockResolvedValue(CORRECTABLE_REPORT); // ok: false, every call

    let call = 0;
    vi.mocked(streamChat).mockImplementation(async (_messages, _settings, onEvent) => {
      call += 1;
      if (call === 1) {
        await onEvent(proposalEvent([{ target_node: "root.thickness_mm", requested_value: 5 }]));
      } else {
        // round 2: a pure-prose reply that resolves a scope/clarification question in prose only --
        // zero ops proposed, so appliedGeometry stays false for this turn.
        await onEvent({ type: "token", text: "noted, still working on it" });
      }
      await onEvent({ type: "done" });
    });

    // No apiKey -- suppresses the BUILT-IN auto-correct queue (shouldAutoCorrect(report) && ... &&
    // settings.apiKey), isolating exactly the behavior under test: a manually-sent, zero-applied-ops
    // turn still re-running the self-check because the PRIOR report was unresolved -- not because the
    // auto-correct loop itself queued this turn.
    render(<Chat {...baseProps()} settings={{ ...settings, apiKey: "" }} onValidate={onValidate} />);
    sendMessage("make it 5mm thick");
    await waitFor(() => expect(onValidate).toHaveBeenCalledTimes(1));

    sendMessage("what's the status on that?");
    await waitFor(() => expect(onValidate).toHaveBeenCalledTimes(2));
  });

  it("does not call onValidate again on a turn that applies zero ops when the prior report was already ok: true", async () => {
    vi.mocked(fetchModelVisionCapable).mockResolvedValue(false);
    vi.mocked(fetchBlueprintDataUrl).mockResolvedValue(BLUEPRINT_URL);
    const onValidate = vi.fn().mockResolvedValue(makeReport()); // ok: true, every call

    let call = 0;
    vi.mocked(streamChat).mockImplementation(async (_messages, _settings, onEvent) => {
      call += 1;
      if (call === 1) {
        await onEvent(proposalEvent([{ target_node: "root.thickness_mm", requested_value: 5 }]));
      } else {
        await onEvent({ type: "token", text: "noted" });
      }
      await onEvent({ type: "done" });
    });

    render(<Chat {...baseProps()} onValidate={onValidate} />);
    sendMessage("make it 5mm thick");
    await waitFor(() => expect(onValidate).toHaveBeenCalledTimes(1));

    sendMessage("what's the status on that?");
    await waitFor(() => expect(screen.getByText(/noted/)).toBeInTheDocument());
    // existing, correct common-case behavior must stay unchanged: a zero-applied-ops turn following an
    // already-resolved (ok: true) report must NOT re-trigger the self-check.
    expect(onValidate).toHaveBeenCalledTimes(1);
  });
});
