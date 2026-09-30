import { countedSavings } from "./savings";
import type { Confirmation, Finding, ScanResult } from "./types";

/**
 * Client-side exports of the findings currently shown in the table. Works in
 * every mode (including the backend-less hosted demo) and sends nothing
 * anywhere: the file is built in the browser and saved locally.
 */

type Confirmations = Record<string, Confirmation | undefined>;

const RISK_LABEL: Record<string, string> = {
  safe: "Safe",
  restart: "Needs restart",
  destructive: "Deletes data",
  commitment: "Commitment",
  info: "Investigate",
};

const ANSWER_LABEL: Record<string, string> = {
  pending: "Asked, waiting",
  keep: "Owner: keep",
  delete_ok: "Owner: OK to delete",
};

function riskLabel(f: Finding): string {
  const level = f.guidance?.risk_level;
  if (level) return RISK_LABEL[level] ?? level;
  return f.fix_destructive ? "Deletes data" : "Review";
}

function ownerLabel(f: Finding): string {
  const o = f.owner;
  if (!o || o.source === "unknown") return "";
  return o.name ?? "";
}

/** Account-wide rows (commitments, anomalies) have no single owner. */
function ownerOrDash(f: Finding): string {
  if (f.category === "commitment" || f.category === "anomaly") return "—";
  return ownerLabel(f) || "unknown";
}

function ownerSource(f: Finding): string {
  const o = f.owner;
  if (!o) return "";
  if (o.source === "tag") return `tag:${o.tag_key}`;
  if (o.source === "cloudtrail")
    return `cloudtrail:${o.event_name ?? ""} ${o.event_time?.slice(0, 10) ?? ""}`.trim();
  return "unknown";
}

// --- CSV -------------------------------------------------------------------------

/** Quote a cell, and neutralise spreadsheet formulas: resource names and tags
 *  come from AWS and could start with =, +, - or @ (CSV injection). */
function cell(value: unknown): string {
  let s = value == null ? "" : String(value);
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(
  scan: ScanResult,
  findings: Finding[],
  answers: Confirmations,
): string {
  const header = [
    "severity",
    "monthly_savings_usd",
    "counted_in_total",
    "category",
    "risk",
    "title",
    "region",
    "resource_id",
    "resource_arn",
    "service",
    "check_id",
    "confidence",
    "recommendation",
    "risks",
    "before_you_act",
    "how_to_undo",
    "reversible",
    "fix_command",
    "fix_deletes_data",
    "owner",
    "owner_source",
    "owner_answer",
    "answered_by",
    "answer_note",
    "account_id",
    "scan_id",
    "detected_at",
  ];
  const rows = findings.map((f) => {
    const g = f.guidance;
    const a = answers[f.id];
    return [
      f.severity,
      f.monthly_savings_usd.toFixed(2),
      f.superseded_by ? "no (alternative)" : "yes",
      f.category ?? "waste",
      riskLabel(f),
      f.title,
      f.region,
      f.resource_id,
      f.resource_arn,
      f.service,
      f.check_id,
      f.confidence,
      g?.recommendation ?? "",
      g?.risks.join(" | ") ?? "",
      g?.before_you_act.join(" | ") ?? "",
      g?.undo ?? "",
      g ? (g.reversible ? "yes" : "no") : "",
      f.cli_fix_command,
      f.fix_destructive ? "yes" : "no",
      ownerLabel(f),
      ownerSource(f),
      a ? (ANSWER_LABEL[a.status] ?? a.status) : "",
      a?.responder ?? "",
      a?.note ?? "",
      scan.account_id ?? "",
      scan.scan_id,
      f.detected_at,
    ]
      .map(cell)
      .join(",");
  });
  // BOM so Excel opens UTF-8 (→, é, emoji) correctly.
  return "﻿" + [header.join(","), ...rows].join("\r\n") + "\r\n";
}

// --- Markdown (change-ticket friendly) -----------------------------------------

function money(n: number): string {
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function mdEscape(s: string): string {
  return s.replace(/\|/g, "\\|");
}

export function toMarkdown(
  scan: ScanResult,
  findings: Finding[],
  answers: Confirmations,
): string {
  const total = findings.reduce((acc, f) => acc + countedSavings(f), 0);
  const lines: string[] = [
    "# AWS cost findings",
    "",
    `- **Account:** ${scan.account_id ?? "—"}${scan.is_demo ? " (demo data)" : ""}`,
    `- **Scanned:** ${scan.finished_at ?? scan.started_at} · ${scan.regions_scanned.length} regions · idle lookback ${scan.lookback_days ?? 7} days`,
    `- **Findings in this export:** ${findings.length} · **est. savings** ${money(total)}/mo (${money(total * 12)}/yr)`,
    "- Estimates use public on-demand pricing; confirm each resource before acting. The scan is read-only.",
    "",
    "| # | $/mo | Risk | Finding | Region | Owner | Owner answer |",
    "|---|---:|---|---|---|---|---|",
    ...findings.map((f, i) => {
      const a = answers[f.id];
      return `| ${i + 1} | ${f.superseded_by ? `~~${money(f.monthly_savings_usd)}~~` : money(f.monthly_savings_usd)} | ${riskLabel(f)} | ${mdEscape(f.title)} | ${f.region} | ${mdEscape(ownerOrDash(f))} | ${a ? ANSWER_LABEL[a.status] : "—"} |`;
    }),
    "",
  ];

  findings.forEach((f, i) => {
    const g = f.guidance;
    const a = answers[f.id];
    lines.push(
      `## ${i + 1}. ${f.title}`,
      "",
      `- **Resource:** \`${f.resource_id}\` (${f.region}) — \`${f.resource_arn}\``,
      `- **Saves:** ${money(f.monthly_savings_usd)}/mo${f.superseded_by ? " (alternative, not counted in the total)" : ""} · **Risk:** ${riskLabel(f)} · **Confidence:** ${f.confidence}`,
      `- **Owner:** ${ownerOrDash(f)}${ownerSource(f) ? ` (${ownerSource(f)})` : ""}`,
    );
    if (a) {
      lines.push(
        `- **Owner answer:** ${ANSWER_LABEL[a.status]}${a.responder ? ` — ${a.responder}` : ""}${a.answered_at ? ` on ${a.answered_at.slice(0, 10)}` : ""}${a.note ? ` — “${a.note}”` : ""}`,
      );
    }
    lines.push("", `**Why:** ${f.description}`, "");
    if (g) {
      lines.push(
        `**Recommendation:** ${g.recommendation}`,
        "",
        "**Risk:**",
        ...g.risks.map((r) => `- ${r}`),
        "",
        "**Before you act:**",
        ...g.before_you_act.map((b) => `- [ ] ${b}`),
        "",
        `**How to undo:** ${g.reversible ? "" : "**Not reversible.** "}${g.undo}`,
        "",
      );
    }
    lines.push("**Fix command:**", "", "```bash", f.cli_fix_command, "```", "");
  });
  return lines.join("\n");
}

// --- JSON ----------------------------------------------------------------------------

export function toJson(
  scan: ScanResult,
  findings: Finding[],
  answers: Confirmations,
): string {
  return JSON.stringify(
    {
      account_id: scan.account_id,
      scan_id: scan.scan_id,
      scanned_at: scan.finished_at ?? scan.started_at,
      regions_scanned: scan.regions_scanned,
      lookback_days: scan.lookback_days,
      is_demo: scan.is_demo,
      findings: findings.map((f) => ({
        ...f,
        owner_answer: answers[f.id] ?? null,
      })),
    },
    null,
    2,
  );
}

// --- saving ----------------------------------------------------------------------------

export type ExportFormat = "csv" | "md" | "json";

const MIME: Record<ExportFormat, string> = {
  csv: "text/csv;charset=utf-8",
  md: "text/markdown;charset=utf-8",
  json: "application/json",
};

export function downloadFindings(
  format: ExportFormat,
  scan: ScanResult,
  findings: Finding[],
  answers: Confirmations,
): void {
  const body =
    format === "csv"
      ? toCsv(scan, findings, answers)
      : format === "md"
        ? toMarkdown(scan, findings, answers)
        : toJson(scan, findings, answers);
  const date = (scan.finished_at ?? scan.started_at).slice(0, 10);
  const name = `aws-findings-${scan.account_id ?? "account"}-${date}.${format}`;
  const url = URL.createObjectURL(new Blob([body], { type: MIME[format] }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
