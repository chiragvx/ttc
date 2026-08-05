import { describe, expect, it } from "vitest";
import { exportConversationToMarkdown } from "./exportConversation";
import type { ChatMessage } from "../types";

const STAMP = new Date("2026-08-04T12:00:00.000Z");

describe("exportConversationToMarkdown", () => {
  it("renders an empty conversation cleanly", () => {
    const md = exportConversationToMarkdown([], STAMP);
    expect(md).toContain("# Conversation export");
    expect(md).toContain("0 message(s)");
  });

  it("renders a user message under a 'You' heading and an assistant message under 'CAD copilot'", () => {
    const messages: ChatMessage[] = [
      { id: "u1", role: "user", text: "make it 3mm thicker" },
      { id: "a1", role: "assistant", text: "done — skin is now 5mm" },
    ];
    const md = exportConversationToMarkdown(messages, STAMP);
    expect(md).toContain("## You");
    expect(md).toContain("make it 3mm thicker");
    expect(md).toContain("## CAD copilot");
    expect(md).toContain("done — skin is now 5mm");
  });

  it("includes instance_op outcomes with their real status and instance id", () => {
    const messages: ChatMessage[] = [{
      id: "a1", role: "assistant", text: "added a bracket",
      instanceOps: [{ op: "add_instance", subsystem_type: "bracket", instance_id: "brk_1" } as any],
      instanceOpOutcomes: [{ op: {} as any, status: "APPLIED", instanceId: "brk_1", subsystemType: "bracket" }],
    }];
    const md = exportConversationToMarkdown(messages, STAMP);
    expect(md).toContain("instance_op add_instance");
    expect(md).toContain("brk_1");
    expect(md).toContain("APPLIED");
  });

  it("includes a REJECTED instance_op's reason, not just the bare status", () => {
    // 2026-08-04 regression: a real exported transcript showed "instance_op add_instance
    // (spur_gear) `pinion_2`: REJECTED" with NO reason anywhere -- InstanceOpOutcome.reason exists
    // on the type but was never read here, so a genuinely useful diagnostic (why did this fail?)
    // was silently dropped from every export.
    const messages: ChatMessage[] = [{
      id: "a1", role: "assistant", text: "",
      instanceOps: [{ op: "add_instance", subsystem_type: "spur_gear", instance_id: "pinion_2" } as any],
      instanceOpOutcomes: [{ op: {} as any, status: "REJECTED", instanceId: null, subsystemType: null,
        reason: "instance id 'pinion_2' already exists" }],
    }];
    const md = exportConversationToMarkdown(messages, STAMP);
    expect(md).toContain("REJECTED");
    expect(md).toContain("instance id 'pinion_2' already exists");
  });

  it("includes a REJECTED op's reason/message, not just the status", () => {
    const messages: ChatMessage[] = [{
      id: "a1", role: "assistant", text: "",
      connectionOps: [{ op: "add_connection", a_instance: "w1", a_interface: "root", b_instance: "b1", b_interface: "tip" } as any],
      connectionOpOutcomes: [{ op: {} as any, status: "REJECTED", connectionId: null, message: "no interface 'tip'" }],
    }];
    const md = exportConversationToMarkdown(messages, STAMP);
    expect(md).toContain("REJECTED");
    expect(md).toContain("no interface 'tip'");
  });

  it("embeds a message's blueprintImage as an inline markdown image with the exact data: URL", () => {
    const dataUrl = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";
    const messages: ChatMessage[] = [{
      id: "a1", role: "assistant", text: "added a bracket",
      blueprintImage: dataUrl,
    } as any];
    const md = exportConversationToMarkdown(messages, STAMP);
    expect(md).toContain(`![blueprint](${dataUrl})`);
  });

  it("emits no image markup for a message without a blueprintImage (the common case)", () => {
    const messages: ChatMessage[] = [
      { id: "u1", role: "user", text: "make it 3mm thicker" },
      { id: "a1", role: "assistant", text: "done — skin is now 5mm" },
    ];
    const md = exportConversationToMarkdown(messages, STAMP);
    expect(md).not.toContain("![blueprint]");
    expect(md).not.toContain("data:image");
  });

  it("surfaces the self-check verdict when present", () => {
    const messages: ChatMessage[] = [{
      id: "a1", role: "assistant", text: "",
      validation: { ok: false, geometric: { ok: false, issues: [], summary: "" }, structural: { ok: true, issues: [], summary: "" }, visual: null } as any,
    }];
    const md = exportConversationToMarkdown(messages, STAMP);
    expect(md).toContain("Self-check: issues found");
  });
});
