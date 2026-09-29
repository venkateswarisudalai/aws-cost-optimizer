"use client";

import {
  AlertTriangle,
  ChevronRight,
  Clock,
  ListChecks,
  Lightbulb,
  ClipboardCheck,
  Search,
  Undo2,
} from "lucide-react";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { idleHint } from "../lib/findingHints";
import { regionLabel } from "../lib/regions";
import { listConfirmations, syncConfirmations } from "../lib/api";
import type { Confirmation, Finding, RiskLevel, ScanResult } from "../lib/types";
import { CategoryBadge } from "./CategoryBadge";
import { CopyButton } from "./CopyButton";
import { ConfirmationBadge, OwnerPanel } from "./OwnerPanel";
import { RiskBadge } from "./RiskBadge";
import { SeverityBadge } from "./SeverityBadge";

function fmtMoney(n: number): string {
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

const selectCls =
  "rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-gray-200 outline-none transition focus:border-emerald-500/60 focus:ring-2 focus:ring-emerald-500/20";

export function FindingsTable({ scan }: { scan: ScanResult }) {
  const [severity, setSeverity] = useState("all");
  const [region, setRegion] = useState("all");
  const [category, setCategory] = useState("all");
  const [risk, setRisk] = useState("all");
  const [q, setQ] = useState("");
  const [confirmations, setConfirmations] = useState<Record<string, Confirmation>>({});
  const [syncing, setSyncing] = useState(false);
  const [syncNote, setSyncNote] = useState<string | null>(null);

  const index = (rows: Confirmation[]) =>
    setConfirmations(Object.fromEntries(rows.map((c) => [c.finding_id, c])));

  const refresh = useCallback(() => {
    listConfirmations().then(index).catch(() => {});
  }, []);
  useEffect(refresh, [refresh, scan]);

  async function checkReplies() {
    setSyncing(true);
    setSyncNote(null);
    try {
      const res = await syncConfirmations();
      index(res.confirmations);
      setSyncNote(
        res.errors.length
          ? `${res.updated} updated · ${res.errors.length} error(s): ${res.errors[0]}`
          : `${res.updated} new answer${res.updated === 1 ? "" : "s"}`,
      );
    } catch (e) {
      setSyncNote(e instanceof Error ? e.message : String(e));
    } finally {
      setSyncing(false);
    }
  }
  const pending = Object.values(confirmations).filter((c) => c.status === "pending").length;

  // Every region the scan covered (not just those with findings), plus
  // "global" for account-wide checks, each with its finding count.
  const regionCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const r of scan.regions_scanned) counts.set(r, 0);
    for (const f of scan.findings) counts.set(f.region, (counts.get(f.region) ?? 0) + 1);
    return Array.from(counts.entries()).sort(([a], [b]) =>
      a === "global" ? -1 : b === "global" ? 1 : a.localeCompare(b),
    );
  }, [scan]);

  const filtered = useMemo(() => {
    return scan.findings.filter((f) => {
      if (severity !== "all" && f.severity !== severity) return false;
      if (region !== "all" && f.region !== region) return false;
      if (category !== "all" && (f.category ?? "waste") !== category)
        return false;
      if (risk !== "all" && riskOf(f) !== risk) return false;
      if (
        q &&
        !`${f.title} ${f.check_id} ${f.resource_id}`
          .toLowerCase()
          .includes(q.toLowerCase())
      )
        return false;
      return true;
    });
  }, [scan, severity, region, category, risk, q]);

  return (
    <section className="rounded-2xl border border-white/10 bg-white/[0.02]">
      <div className="flex flex-col gap-3 border-b border-white/10 p-5 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-2">
          <ListChecks size={16} className="text-gray-400" />
          <div>
            <h2 className="text-sm font-semibold tracking-tight text-white">
              Findings
            </h2>
            <p className="text-xs text-gray-500">
              Sorted by monthly savings · {filtered.length} shown
            </p>
            {Object.keys(confirmations).length > 0 && (
              <button
                onClick={checkReplies}
                disabled={syncing}
                className="mt-1 text-xs font-medium text-emerald-400 hover:text-emerald-300 disabled:opacity-50"
              >
                {syncing ? "Checking Slack…" : `Check Slack replies${pending ? ` (${pending} waiting)` : ""}`}
              </button>
            )}
            {syncNote && <p className="text-[11px] text-gray-500">{syncNote}</p>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <div className="relative">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500"
            />
            <input
              className="w-52 rounded-lg border border-white/10 bg-white/[0.03] py-2 pl-9 pr-3 text-sm text-gray-100 placeholder-gray-600 outline-none transition focus:border-emerald-500/60 focus:ring-2 focus:ring-emerald-500/20"
              placeholder="Search findings…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <select
            className={selectCls}
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="all">All categories</option>
            <option value="waste">Waste</option>
            <option value="rightsizing">Rightsizing</option>
            <option value="commitment">Commitment (RI/SP)</option>
            <option value="anomaly">Anomaly</option>
            <option value="hygiene">Hygiene ($0, security)</option>
          </select>
          <select
            className={selectCls}
            value={risk}
            onChange={(e) => setRisk(e.target.value)}
            aria-label="Filter by risk"
          >
            <option value="all">All risk levels</option>
            <option value="safe">Safe to apply</option>
            <option value="restart">Needs restart</option>
            <option value="destructive">Deletes data</option>
            <option value="commitment">Commitment</option>
            <option value="info">Investigate</option>
          </select>
          <select
            className={selectCls}
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
          >
            <option value="all">All severities</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <select
            className={selectCls}
            value={region}
            onChange={(e) => setRegion(e.target.value)}
          >
            <option value="all">All regions ({scan.regions_scanned.length})</option>
            {regionCounts.map(([r, n]) => (
              <option key={r} value={r}>
                {r === "global" ? "global · account-wide" : regionLabel(r)} ({n})
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/10 text-left text-xs uppercase tracking-wide text-gray-500">
              <th className="w-8 py-3 pl-4" aria-label="Expand" />
              <th className="px-3 py-3 font-medium">Sev</th>
              <th className="px-3 py-3 text-right font-medium">$ / mo</th>
              <th className="px-3 py-3 font-medium">Finding</th>
              <th className="px-3 py-3 font-medium">Region</th>
              <th className="px-3 py-3 font-medium">Idle / last used</th>
              <th className="px-3 py-3 font-medium">Fix</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {filtered.map((f) => (
              <FindingRow
                key={f.id}
                f={f}
                confirmation={confirmations[f.id]}
                onAsked={refresh}
              />
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={7} className="px-5 py-10 text-center text-sm text-gray-500">
                  No findings match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** Risk level from the server's guidance, or a conservative fallback for scans
 *  saved before guidance existed. */
function riskOf(f: Finding): RiskLevel {
  if (f.guidance) return f.guidance.risk_level;
  if (f.category === "commitment") return "commitment";
  if (f.category === "anomaly") return "info";
  return f.fix_destructive ? "destructive" : "restart";
}

function FindingRow({
  f,
  confirmation,
  onAsked,
}: {
  f: Finding;
  confirmation?: Confirmation;
  onAsked: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Fragment>
    <tr
      className={`group cursor-pointer transition-colors hover:bg-white/[0.025] ${open ? "bg-white/[0.025]" : ""}`}
      onClick={() => setOpen((o) => !o)}
    >
      <td className="py-3 pl-4 align-top">
        <button
          aria-expanded={open}
          aria-label={open ? "Hide guidance" : "Show guidance"}
          className="rounded p-0.5 text-gray-500 hover:text-gray-200"
        >
          <ChevronRight
            size={15}
            className={`transition-transform ${open ? "rotate-90" : ""}`}
          />
        </button>
      </td>
      <td className="px-3 py-3 align-top">
        <SeverityBadge severity={f.severity} />
      </td>
      <td
        className={`whitespace-nowrap px-3 py-3 text-right align-top font-medium tabular-nums ${
          f.superseded_by ? "text-gray-500 line-through decoration-gray-600" : "text-emerald-400"
        }`}
        title={f.superseded_by ? "Alternative option — not counted in totals" : undefined}
      >
        {fmtMoney(f.monthly_savings_usd)}
      </td>
      <td className="px-3 py-3 align-top">
        <div className="flex flex-col">
          <span className="font-medium text-gray-100">{f.title}</span>
          <span className="mt-0.5 max-w-md truncate text-xs text-gray-500">
            {f.description}
          </span>
          <span className="mt-1 flex items-center gap-2">
            <CategoryBadge category={f.category} />
            {/* Commitment / anomaly categories already say what the risk badge would. */}
            {f.category !== "commitment" && f.category !== "anomaly" && (
              <RiskBadge level={riskOf(f)} />
            )}
            <ConfirmationBadge c={confirmation} />
            <span className="font-mono text-[11px] text-gray-600">
              {f.check_id}
            </span>
          </span>
          {f.superseded_by && (
            <span className="mt-1 text-xs text-gray-500">
              Alternative to a bigger saving on the same resource — not added to totals
            </span>
          )}
        </div>
      </td>
      <td className="whitespace-nowrap px-3 py-3 align-top font-mono text-xs text-gray-400">
        {f.region}
      </td>
      <td className="whitespace-nowrap px-3 py-3 align-top">
        <IdleCell f={f} />
      </td>
      <td className="px-3 py-3 align-top" onClick={(e) => e.stopPropagation()}>
        <CopyButton text={f.cli_fix_command} />
      </td>
    </tr>
    {open && (
      <tr className="bg-white/[0.015]">
        <td />
        <td colSpan={6} className="px-3 pb-5 pt-1">
          <GuidancePanel f={f} />
          {f.category !== "commitment" && f.category !== "anomaly" && (
            <div className="sticky left-0 mt-3 w-[min(44rem,calc(100vw-5rem))]">
              <OwnerPanel f={f} confirmation={confirmation} onAsked={onAsked} />
            </div>
          )}
        </td>
      </tr>
    )}
    </Fragment>
  );
}

function GuidancePanel({ f }: { f: Finding }) {
  const g = f.guidance;
  return (
    <div className="sticky left-0 w-[min(44rem,calc(100vw-5rem))] space-y-4 rounded-xl border border-white/10 bg-gray-950/60 p-4 text-sm">
      <p className="text-xs leading-relaxed text-gray-400">{f.description}</p>
      {!g ? (
        <p className="text-xs text-gray-500">
          Detailed guidance isn&apos;t available for this finding. Run a new scan to get it.
        </p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          <Section icon={<Lightbulb size={14} className="text-emerald-400" />} title="Recommendation">
            <p className="text-gray-200">{g.recommendation}</p>
          </Section>
          <Section icon={<AlertTriangle size={14} className="text-rose-400" />} title="Risk">
            <List items={g.risks} />
          </Section>
          <Section icon={<ClipboardCheck size={14} className="text-sky-400" />} title="Before you act">
            <List items={g.before_you_act} />
          </Section>
          <Section icon={<Undo2 size={14} className="text-amber-400" />} title="How to undo">
            <p className={g.reversible ? "text-gray-300" : "text-rose-300"}>
              {!g.reversible && <span className="font-semibold">Not reversible. </span>}
              <Rich text={g.undo} />
            </p>
          </Section>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-white/5 pt-3 text-xs text-gray-500">
        <span>
          Confidence: <span className="text-gray-300">{f.confidence}</span>
          {f.confidence !== "high" && " · check it's really unused before acting"}
        </span>
        <span className="font-mono text-[11px] text-gray-600">{f.resource_arn}</span>
      </div>
    </div>
  );
}

function Section({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
        {icon}
        {title}
      </div>
      <div className="text-xs leading-relaxed">{children}</div>
    </div>
  );
}

function List({ items }: { items: string[] }) {
  return (
    <ul className="list-disc space-y-1 pl-4 text-gray-300 marker:text-gray-600">
      {items.map((t) => (
        <li key={t}>
          <Rich text={t} />
        </li>
      ))}
    </ul>
  );
}

/** Render `backtick` spans as inline code so commands stand out. */
function Rich({ text }: { text: string }) {
  const parts = text.split(/`([^`]+)`/g);
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <code
            key={i}
            className="break-all rounded bg-white/5 px-1 py-0.5 font-mono text-[11px] text-gray-200"
          >
            {p}
          </code>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        ),
      )}
    </>
  );
}

function IdleCell({ f }: { f: Finding }) {
  const hint = idleHint(f);
  if (!hint) return <span className="text-xs text-gray-600">—</span>;
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-white/[0.04] px-2 py-0.5 text-[11px] text-gray-300">
      <Clock size={11} className="text-gray-500" />
      {hint}
    </span>
  );
}
