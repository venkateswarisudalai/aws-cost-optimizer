"use client";

import { AlertTriangle, Clock, ListChecks, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { idleHint } from "../lib/findingHints";
import type { Finding, ScanResult } from "../lib/types";
import { CategoryBadge } from "./CategoryBadge";
import { CopyButton } from "./CopyButton";
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
  const [q, setQ] = useState("");

  const allRegions = useMemo(
    () => Array.from(new Set(scan.findings.map((f) => f.region))).sort(),
    [scan],
  );

  const filtered = useMemo(() => {
    return scan.findings.filter((f) => {
      if (severity !== "all" && f.severity !== severity) return false;
      if (region !== "all" && f.region !== region) return false;
      if (category !== "all" && (f.category ?? "waste") !== category)
        return false;
      if (
        q &&
        !`${f.title} ${f.check_id} ${f.resource_id}`
          .toLowerCase()
          .includes(q.toLowerCase())
      )
        return false;
      return true;
    });
  }, [scan, severity, region, category, q]);

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
            <option value="all">All regions</option>
            {allRegions.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/10 text-left text-xs uppercase tracking-wide text-gray-500">
              <th className="px-5 py-3 font-medium">Sev</th>
              <th className="px-3 py-3 text-right font-medium">$ / mo</th>
              <th className="px-3 py-3 font-medium">Finding</th>
              <th className="px-3 py-3 font-medium">Region</th>
              <th className="px-3 py-3 font-medium">Idle / last used</th>
              <th className="px-3 py-3 font-medium">Fix</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {filtered.map((f) => (
              <FindingRow key={f.id} f={f} />
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-5 py-10 text-center text-sm text-gray-500">
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

function FindingRow({ f }: { f: Finding }) {
  return (
    <tr className="group transition-colors hover:bg-white/[0.025]">
      <td className="px-5 py-3 align-top">
        <SeverityBadge severity={f.severity} />
      </td>
      <td className="whitespace-nowrap px-3 py-3 text-right align-top font-medium tabular-nums text-emerald-400">
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
            <span className="font-mono text-[11px] text-gray-600">
              {f.check_id}
            </span>
          </span>
          {f.fix_destructive && (
            <span className="mt-1 inline-flex items-center gap-1 text-xs text-amber-400">
              <AlertTriangle size={11} />
              Fix deletes data — verify before running
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
      <td className="px-3 py-3 align-top">
        <CopyButton text={f.cli_fix_command} />
      </td>
    </tr>
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
