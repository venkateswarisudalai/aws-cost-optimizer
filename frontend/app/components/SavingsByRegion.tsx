"use client";

import { MapPin } from "lucide-react";
import { regionName } from "../lib/regions";
import type { ScanResult } from "../lib/types";

function fmtMoney(n: number): string {
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

/**
 * Per-region breakdown of the optimisable monthly spend in the current scan.
 * Rows are sorted by savings; clicking one re-scans that region live so you
 * can drill into a single region's waste.
 */
export function SavingsByRegion({
  scan,
  selectedRegion,
  onSelectRegion,
}: {
  scan: ScanResult;
  selectedRegion: string;
  onSelectRegion: (region: string) => void;
}) {
  const totals = new Map<string, { savings: number; count: number }>();
  for (const f of scan.findings) {
    const cur = totals.get(f.region) ?? { savings: 0, count: 0 };
    cur.savings += f.monthly_savings_usd;
    cur.count += 1;
    totals.set(f.region, cur);
  }
  // Surface scanned regions even when they turned up no waste.
  for (const r of scan.regions_scanned) {
    if (!totals.has(r)) totals.set(r, { savings: 0, count: 0 });
  }

  const rows = Array.from(totals.entries())
    .map(([region, v]) => ({ region, ...v }))
    .sort((a, b) => b.savings - a.savings);
  const max = Math.max(1, ...rows.map((r) => r.savings));

  return (
    <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-5">
      <div className="flex items-center gap-2">
        <MapPin size={16} className="text-gray-400" />
        <h2 className="text-sm font-semibold tracking-tight text-white">
          Savings by region
        </h2>
      </div>
      <p className="mt-1 text-xs text-gray-500">
        Click a region to re-scan it live.
      </p>

      <div className="mt-4 space-y-1.5">
        {rows.map((r) => {
          const active = selectedRegion === r.region;
          const pct = Math.round((r.savings / max) * 100);
          return (
            <button
              key={r.region}
              onClick={() => onSelectRegion(r.region)}
              className={`group relative flex w-full items-center gap-3 overflow-hidden rounded-lg px-3 py-2 text-left transition ${
                active
                  ? "bg-emerald-500/10 ring-1 ring-emerald-500/30"
                  : "hover:bg-white/[0.04]"
              }`}
            >
              <span
                className="absolute inset-y-0 left-0 bg-emerald-500/[0.08] transition-all"
                style={{ width: `${pct}%` }}
                aria-hidden
              />
              <span className="relative z-10 flex w-40 shrink-0 flex-col">
                <code className="truncate text-xs text-gray-200">{r.region}</code>
                <span className="truncate text-[10px] text-gray-500">
                  {regionName(r.region)}
                </span>
              </span>
              <span className="relative z-10 flex-1 text-right text-[11px] tabular-nums text-gray-500">
                {r.count} finding{r.count === 1 ? "" : "s"}
              </span>
              <span className="relative z-10 w-16 text-right text-sm font-medium tabular-nums text-emerald-400">
                {fmtMoney(r.savings)}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
