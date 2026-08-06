import type { ChatMessage } from "../types";

// Serializes the chat transcript to a plain-text Markdown document (2026-08-04) — so a user can
// share a full session as a .md file for review, the same way a zoo.dev-style transcript export
// works. Pure/testable (no DOM, no download side effect here — see triggerMarkdownDownload below
// for that), matching this codebase's established "extract the risky pure logic" pattern
// (summarizeOutcomes.ts, buildCorrectionMessage.ts, shouldAutoCorrect.ts).

function statusLine(label: string, status: string, id: string | null, message?: string): string {
  const idPart = id ? ` \`${id}\`` : "";
  const msgPart = message ? ` — ${message}` : "";
  return `- **${label}**${idPart}: ${status}${msgPart}`;
}

function messageOpsSection(m: ChatMessage): string[] {
  const lines: string[] = [];
  m.instanceOps?.forEach((op, i) => {
    const outcome = m.instanceOpOutcomes?.[i];
    lines.push(statusLine(
      `instance_op ${op.op}${op.subsystem_type ? ` (${op.subsystem_type})` : ""}`,
      outcome?.status ?? "pending", outcome?.instanceId ?? op.instance_id ?? null, outcome?.reason,
    ));
  });
  m.featureOps?.forEach((op, i) => {
    const outcome = m.featureOpOutcomes?.[i];
    lines.push(statusLine(`feature_op ${op.op}`, outcome?.status ?? "pending",
      outcome?.instanceId ?? op.instance_id ?? null, outcome?.reason));
  });
  m.connectionOps?.forEach((op, i) => {
    const outcome = m.connectionOpOutcomes?.[i];
    lines.push(statusLine(`connection_op ${op.op}`, outcome?.status ?? "pending",
      outcome?.connectionId ?? null, outcome?.message));
  });
  m.couplingOps?.forEach((op, i) => {
    const outcome = m.couplingOpOutcomes?.[i];
    lines.push(statusLine(`coupling_op ${op.op}`, outcome?.status ?? "pending",
      outcome?.couplingId ?? null, outcome?.message));
  });
  m.fitOps?.forEach((op, i) => {
    const outcome = m.fitOpOutcomes?.[i];
    lines.push(statusLine(`fit_op ${op.op}`, outcome?.status ?? "pending",
      outcome?.fitId ?? null, outcome?.message));
  });
  m.envelopeOps?.forEach((op, i) => {
    const outcome = m.envelopeOpOutcomes?.[i];
    lines.push(statusLine(`envelope_op ${op.op}`, outcome?.status ?? "pending",
      outcome?.housingInstanceId ?? op.housing_instance ?? null, outcome?.message));
  });
  m.joinAnnotationOps?.forEach((op, i) => {
    const outcome = m.joinAnnotationOpOutcomes?.[i];
    lines.push(statusLine(`join_annotation_op ${op.op}`, outcome?.status ?? "pending",
      outcome?.joinId ?? null, outcome?.message));
  });
  m.regionOps?.forEach((op, i) => {
    const outcome = m.regionOpOutcomes?.[i];
    lines.push(statusLine(`region_op ${op.op}`, outcome?.status ?? "pending",
      outcome?.regionId ?? null, outcome?.message));
  });
  m.outcomes?.forEach((o) => {
    lines.push(statusLine(`delta ${o.node}`, o.status, null,
      o.reason ?? `${o.oldValue ?? "?"} -> ${o.applied ?? o.requested}`));
  });
  return lines;
}

export function exportConversationToMarkdown(messages: ChatMessage[], generatedAt: Date = new Date()): string {
  const parts: string[] = [
    "# Conversation export",
    "",
    `Generated ${generatedAt.toISOString()} — ${messages.length} message(s).`,
    "",
  ];

  for (const m of messages) {
    parts.push(`## ${m.role === "user" ? "You" : "CAD copilot"}`, "");
    if (m.text) parts.push(m.text.trim(), "");

    if (m.researchFinding) {
      parts.push(`> Research: ${m.researchFinding.summary ?? "(no summary)"}`, "");
    }
    if (m.scopeProposal) {
      parts.push(`> Scope proposal: ${m.scopeProposal.goal ?? ""} (${m.scopeProposal.parts?.length ?? 0} part(s))`, "");
    }
    if (m.clarification) {
      parts.push(`> Clarification requested: ${m.clarification}`, "");
    }
    if (m.suggestions && m.suggestions.length > 0) {
      parts.push(`> Suggestions: ${m.suggestions.join(" | ")}`, "");
    }

    const opLines = messageOpsSection(m);
    if (opLines.length > 0) {
      parts.push(...opLines, "");
    }

    // Self-contained embed (2026-08-05) — the self-check's rendered blueprint, as a base64 data:
    // URL already assembled client-side (see Chat.tsx), interpolated as-is: no re-encoding, no
    // separate linked file, so the exported .md stays a single shareable artifact. Absent on every
    // message from before this feature existed (and most messages even after) — emit nothing then,
    // same as every other optional section above.
    if (m.blueprintImage) {
      parts.push(`![blueprint](${m.blueprintImage})`, "");
    }

    if (m.validation) {
      const v = m.validation;
      parts.push(`> Self-check: ${v.ok ? "ok" : "issues found"}`, "");
    }
  }

  return parts.join("\n").trimEnd() + "\n";
}

// Browser-only side effect (Blob + object URL download) — kept separate from the pure formatter
// above so the formatter itself stays trivially unit-testable without a DOM.
export function triggerMarkdownDownload(filename: string, markdown: string): void {
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
