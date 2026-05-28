"use client";

import { Github, Plug, RefreshCw, ShieldCheck } from "lucide-react";

export function Header({
  onScan,
  onConnect,
  scanning,
  isDemo,
  connectionLabel,
  regionCount,
}: {
  onScan: () => void;
  onConnect: () => void;
  scanning: boolean;
  isDemo: boolean;
  connectionLabel: string | null;
  regionCount: number;
}) {
  return (
    <header className="sticky top-0 z-20 border-b border-white/10 bg-gray-950/70 backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3.5">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-500 to-blue-600 shadow-lg shadow-emerald-500/20">
            <ShieldCheck size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-[15px] font-semibold tracking-tight text-white">
              aws-cost-optimizer
            </h1>
            <p className="flex items-center gap-1.5 text-xs text-gray-500">
              local-first AWS waste finder
              <span className="text-gray-700">·</span>
              <StatusPill
                isDemo={isDemo}
                connectionLabel={connectionLabel}
                regionCount={regionCount}
              />
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <a
            href="https://github.com/venkateswarisudalai/aws-cost-optimizer"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-sm text-gray-400 transition hover:bg-white/5 hover:text-gray-200"
          >
            <Github size={16} />
            <span className="hidden sm:inline">GitHub</span>
          </a>

          {!isDemo && (
            <button
              onClick={onConnect}
              disabled={scanning}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-3.5 py-2 text-sm font-medium text-gray-200 transition hover:bg-white/[0.07] disabled:opacity-40"
            >
              <Plug size={15} />
              {connectionLabel ? "Change account" : "Connect AWS"}
            </button>
          )}

          <button
            onClick={onScan}
            disabled={(!isDemo && !connectionLabel) || scanning}
            className="inline-flex items-center gap-1.5 rounded-lg bg-gradient-to-br from-emerald-500 to-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-emerald-500/20 transition hover:from-emerald-400 hover:to-emerald-500 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
          >
            <RefreshCw size={15} className={scanning ? "animate-spin" : ""} />
            {scanning
              ? "Scanning…"
              : isDemo
                ? "New scan"
                : connectionLabel
                  ? "Rescan"
                  : "Connect to scan"}
          </button>
        </div>
      </div>
    </header>
  );
}

function StatusPill({
  isDemo,
  connectionLabel,
  regionCount,
}: {
  isDemo: boolean;
  connectionLabel: string | null;
  regionCount: number;
}) {
  if (isDemo) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-medium text-amber-300">
        <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
        demo mode
      </span>
    );
  }
  if (connectionLabel) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-medium text-emerald-300">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        {connectionLabel}
        {regionCount > 0 && (
          <span className="text-emerald-400/60">
            · {regionCount} region{regionCount === 1 ? "" : "s"}
          </span>
        )}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-white/5 px-2 py-0.5 text-[11px] font-medium text-gray-400">
      <span className="h-1.5 w-1.5 rounded-full bg-gray-500" />
      not connected
    </span>
  );
}
