"use client";

import { Loader2, Play, Sparkles } from "lucide-react";

export function EmptyState({
  onScan,
  scanning,
}: {
  onScan: () => void;
  scanning: boolean;
}) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02] px-8 py-16 text-center">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-emerald-500/10 to-transparent" />
      <div className="relative">
        <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.04]">
          <Sparkles size={24} className="text-emerald-400" />
        </div>
        <h2 className="text-xl font-semibold tracking-tight text-white">
          No findings yet
        </h2>
        <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-gray-400">
          Run a scan to surface idle and orphaned resources that are quietly
          costing you money.
        </p>
        <button
          onClick={onScan}
          disabled={scanning}
          className="mt-7 inline-flex items-center gap-2 rounded-lg bg-gradient-to-br from-emerald-500 to-emerald-600 px-5 py-2.5 text-sm font-medium text-white shadow-lg shadow-emerald-500/20 transition hover:from-emerald-400 hover:to-emerald-500 disabled:opacity-50"
        >
          {scanning ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              Scanning…
            </>
          ) : (
            <>
              <Play size={16} />
              Run scan
            </>
          )}
        </button>
      </div>
    </div>
  );
}
