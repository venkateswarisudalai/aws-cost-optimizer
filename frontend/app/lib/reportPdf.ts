import { countedSavings } from "./savings";
import type { Confirmation, Finding, ScanResult } from "./types";

/**
 * A print-ready HTML report, opened in a new tab with the print dialog up so
 * "Save as PDF" produces the file. No PDF library: the browser's own print
 * engine gives real text (searchable, copyable) and correct page breaks.
 *
 * Every value that came from AWS (names, tags, descriptions) is HTML-escaped.
 */

type Confirmations = Record<string, Confirmation | undefined>;

const RISK: Record<string, { label: string; color: string }> = {
  safe: { label: "Safe", color: "#047857" },
  restart: { label: "Needs restart", color: "#0369a1" },
  destructive: { label: "Deletes data", color: "#b91c1c" },
  commitment: { label: "Commitment", color: "#6d28d9" },
  info: { label: "Investigate", color: "#4b5563" },
};

const ANSWER: Record<string, string> = {
  pending: "Asked, waiting",
  keep: "Keep",
  delete_ok: "OK to delete",
};

function esc(v: unknown): string {
  return String(v ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Escape, then render `backtick` spans as code. */
function rich(v: string): string {
  return esc(v).replace(/`([^`]+)`/g, "<code>$1</code>");
}

function money(n: number, frac = 2): string {
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: frac, maximumFractionDigits: frac })}`;
}

function risk(f: Finding) {
  const level =
    f.guidance?.risk_level ?? (f.fix_destructive ? "destructive" : "restart");
  return RISK[level] ?? RISK.info;
}

function owner(f: Finding): string {
  const o = f.owner;
  // Commitments and anomalies are account-wide: no single owner.
  if (f.category === "commitment" || f.category === "anomaly") return "—";
  if (!o || o.source === "unknown") return "Unknown";
  if (o.source === "tag") return `${o.name} (tag: ${o.tag_key})`;
  return `${o.name} (CloudTrail: ${o.event_name}${o.event_time ? `, ${o.event_time.slice(0, 10)}` : ""})`;
}

const CSS = `
  @page { size: A4; margin: 16mm 14mm; }
  * { box-sizing: border-box; }
  body { font: 10.5pt/1.45 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         color: #111827; margin: 0; background: #fff; }
  h1 { font-size: 20pt; margin: 0 0 2mm; letter-spacing: -0.01em; }
  h2 { font-size: 13pt; margin: 8mm 0 3mm; }
  h3 { font-size: 11pt; margin: 0 0 2mm; }
  .muted { color: #6b7280; }
  .kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 3mm; margin: 5mm 0; }
  .kpi { border: 1px solid #e5e7eb; border-radius: 3mm; padding: 3mm 4mm; }
  .kpi b { display: block; font-size: 15pt; margin-top: 1mm; }
  .kpi.hero b { color: #047857; }
  table { width: 100%; border-collapse: collapse; font-size: 9pt; }
  th { text-align: left; color: #6b7280; font-weight: 600; border-bottom: 1.5px solid #d1d5db;
       padding: 1.6mm 1.5mm; }
  td { border-bottom: 1px solid #eef0f3; padding: 1.6mm 1.5mm; vertical-align: top; }
  thead { display: table-header-group; }
  tr { break-inside: avoid; }
  .nowrap { white-space: nowrap; }
  .num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .alt { color: #9ca3af; text-decoration: line-through; }
  .pill { display: inline-block; border: 1px solid currentColor; border-radius: 2mm;
          padding: 0 1.5mm; font-size: 8pt; font-weight: 600; white-space: nowrap; }
  .card { border: 1px solid #e5e7eb; border-radius: 3mm; padding: 4mm; margin: 0 0 4mm;
          break-inside: avoid; }
  .meta { font-size: 9pt; color: #374151; margin: 0 0 2mm; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 2mm 6mm; margin-top: 2mm; }
  .label { font-size: 8pt; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
           color: #6b7280; margin: 2mm 0 0.5mm; }
  ul { margin: 0; padding-left: 4.5mm; }
  li { margin: 0.4mm 0; }
  ul.check { list-style: none; padding-left: 0; }
  ul.check li::before { content: "☐  "; }
  code, pre { font: 8.5pt/1.4 ui-monospace, Menlo, Consolas, monospace; }
  code { background: #f3f4f6; padding: 0 1mm; border-radius: 1mm; word-break: break-all; }
  pre { background: #f3f4f6; padding: 2.5mm; border-radius: 2mm; white-space: pre-wrap;
        word-break: break-all; margin: 1mm 0 0; }
  .warn { color: #b91c1c; font-weight: 600; }
  .sign { margin-top: 3mm; display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6mm;
          font-size: 8.5pt; color: #6b7280; }
  .sign div { border-top: 1px solid #9ca3af; padding-top: 1mm; }
  .page-break { break-before: page; }
  footer { margin-top: 8mm; font-size: 8pt; color: #9ca3af; }
  @media screen { body { max-width: 210mm; margin: 10mm auto; padding: 0 8mm; } }
`;

export function toReportHtml(
  scan: ScanResult,
  findings: Finding[],
  answers: Confirmations,
): string {
  const total = findings.reduce((a, f) => a + countedSavings(f), 0);
  const safe = findings
    .filter((f) => f.guidance?.risk_level === "safe")
    .reduce((a, f) => a + countedSavings(f), 0);
  const spend = scan.spend;
  const monthly = spend?.forecast_month_usd ?? spend?.total_30d_usd ?? null;
  const scanned = new Date(scan.finished_at ?? scan.started_at);

  const summaryRows = findings
    .map((f, i) => {
      const r = risk(f);
      const a = answers[f.id];
      return `<tr>
        <td class="num">${i + 1}</td>
        <td class="num ${f.superseded_by ? "alt" : ""}">${money(f.monthly_savings_usd)}</td>
        <td><span class="pill" style="color:${r.color}">${r.label}</span></td>
        <td>${esc(f.title)}</td>
        <td class="nowrap">${esc(f.region)}</td>
        <td>${esc(owner(f))}</td>
        <td>${a ? esc(ANSWER[a.status] ?? a.status) : "—"}</td>
      </tr>`;
    })
    .join("");

  const details = findings
    .map((f, i) => {
      const g = f.guidance;
      const r = risk(f);
      const a = answers[f.id];
      return `<section class="card">
        <h3>${i + 1}. ${esc(f.title)}</h3>
        <p class="meta">
          <span class="pill" style="color:${r.color}">${r.label}</span>
          &nbsp;<b>${money(f.monthly_savings_usd)}/mo</b>${f.superseded_by ? " (alternative, not in total)" : ""}
          · ${esc(f.region)} · <code>${esc(f.resource_id)}</code> · confidence ${esc(f.confidence)}
        </p>
        <p class="meta">Owner: ${esc(owner(f))}${
          a
            ? ` · Answer: <b>${esc(ANSWER[a.status] ?? a.status)}</b>${a.responder ? ` by ${esc(a.responder)}` : ""}${a.note ? ` — “${esc(a.note)}”` : ""}`
            : ""
        }</p>
        <p class="meta muted">${esc(f.description)}</p>
        ${
          g
            ? `<div class="label">Recommendation</div><div>${rich(g.recommendation)}</div>
        <div class="grid">
          <div><div class="label">Risk</div><ul>${g.risks.map((x) => `<li>${rich(x)}</li>`).join("")}</ul></div>
          <div><div class="label">Before you act</div><ul class="check">${g.before_you_act.map((x) => `<li>${rich(x)}</li>`).join("")}</ul></div>
        </div>
        <div class="label">How to undo</div>
        <div>${g.reversible ? "" : '<span class="warn">Not reversible.</span> '}${rich(g.undo)}</div>`
            : ""
        }
        <div class="label">Fix command</div>
        <pre>${esc(f.cli_fix_command)}</pre>
        <div class="sign"><div>Approved by</div><div>Date</div><div>Change ticket #</div></div>
      </section>`;
    })
    .join("");

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AWS cost report · ${esc(scan.account_id ?? "account")} · ${scanned.toISOString().slice(0, 10)}</title>
<style>${CSS}</style></head>
<body>
  <h1>AWS cost report</h1>
  <div class="muted">
    Account <b>${esc(scan.account_id ?? "—")}</b>${scan.is_demo ? " (demo data)" : ""} ·
    scanned ${esc(scanned.toLocaleString())} · ${scan.regions_scanned.length} regions ·
    idle lookback ${scan.lookback_days ?? 7} days
  </div>

  <div class="kpis">
    <div class="kpi hero">Est. savings<b>${money(total, 0)}/mo</b><span class="muted">${money(total * 12, 0)} per year</span></div>
    <div class="kpi">Current bill<b>${monthly != null ? `${money(monthly, 0)}/mo` : "—"}</b><span class="muted">${spend ? "Cost Explorer" : "not available"}</span></div>
    <div class="kpi">After fixes<b>${monthly != null ? `${money(Math.max(0, monthly - total), 0)}/mo` : "—"}</b><span class="muted">${monthly ? `−${Math.min(100, (total / monthly) * 100).toFixed(0)}%` : ""}</span></div>
    <div class="kpi">Safe to apply now<b>${money(safe, 0)}/mo</b><span class="muted">no downtime, reversible</span></div>
  </div>

  <p class="muted">
    ${findings.length} findings. Savings are estimates from public on-demand prices; alternatives for the
    same resource are struck through and not counted. The scan is read-only: nothing has been changed.
    Confirm each item with its owner before acting.
  </p>

  <h2>Summary</h2>
  <table>
    <thead><tr><th class="num">#</th><th class="num">$/mo</th><th>Risk</th><th>Finding</th><th>Region</th><th>Owner</th><th>Owner answer</th></tr></thead>
    <tbody>${summaryRows}</tbody>
  </table>

  <h2 class="page-break">Details</h2>
  ${details}

  <footer>Generated by aws-cost-optimizer · read-only scan · ${esc(new Date().toISOString())}</footer>
</body></html>`;
}

/** Open the report and bring up the print dialog ("Save as PDF"). */
export function printReport(
  scan: ScanResult,
  findings: Finding[],
  answers: Confirmations,
): void {
  const html = toReportHtml(scan, findings, answers);
  const url = URL.createObjectURL(
    new Blob([html], { type: "text/html;charset=utf-8" }),
  );
  const win = window.open(url, "_blank");
  if (!win) {
    // Pop-up blocked: fall back to saving the HTML, which prints the same way.
    const a = document.createElement("a");
    a.href = url;
    a.download = `aws-cost-report-${scan.account_id ?? "account"}.html`;
    a.click();
    return;
  }
  win.addEventListener("load", () => {
    win.focus();
    win.print();
  });
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
