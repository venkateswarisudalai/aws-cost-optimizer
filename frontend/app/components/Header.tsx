"use client";

import { Button } from "@tremor/react";
import { Github, RefreshCw, ShieldCheck } from "lucide-react";

export function Header({
  onScan,
  scanning,
  isDemo,
}: {
  onScan: () => void;
  scanning: boolean;
  isDemo: boolean;
}) {
  return (
    <header className="border-b border-gray-800 bg-gray-950/70 backdrop-blur sticky top-0 z-10">
      <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-emerald-500 to-blue-600 flex items-center justify-center">
            <ShieldCheck size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight">
              aws-cost-optimizer
            </h1>
            <p className="text-xs text-gray-500">
              local-first AWS waste finder ·{" "}
              {isDemo ? (
                <span className="text-amber-400">demo mode</span>
              ) : (
                <span className="text-emerald-400">your creds, your laptop</span>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <a
            href="https://github.com/venkateswarisudalai/aws-cost-optimizer"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-200 px-2 py-1"
          >
            <Github size={16} />
            GitHub
          </a>
          <Button
            icon={RefreshCw}
            loading={scanning}
            loadingText="Scanning…"
            onClick={onScan}
            variant="primary"
          >
            New scan
          </Button>
        </div>
      </div>
    </header>
  );
}
