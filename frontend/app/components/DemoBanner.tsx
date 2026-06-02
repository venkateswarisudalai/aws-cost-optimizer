"use client";

import { Github, Lock, Terminal } from "lucide-react";
import { CopyButton } from "./CopyButton";

const REPO = "https://github.com/venkateswarisudalai/aws-cost-optimizer";

const STEPS: { label: string; cmd: string }[] = [
  { label: "1. Clone the repo", cmd: `git clone ${REPO}` },
  { label: "2. Install (read-only)", cmd: "cd aws-cost-optimizer/backend && pip install -e ." },
  { label: "3. Scan your account", cmd: "awsco scan" },
];

/**
 * Shown only on the hosted showcase build. The hosted dashboard runs on sample
 * data; the real value is running it locally against your own account, where
 * your AWS credentials never leave your machine. This banner is the call to do
 * exactly that.
 */
export function DemoBanner() {
  return (
    <div className="overflow-hidden rounded-2xl border border-emerald-500/25 bg-gradient-to-br from-emerald-500/[0.08] to-blue-600/[0.05]">
      <div className="flex flex-col gap-5 px-6 py-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="max-w-xl">
          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-emerald-300/80">
            <Terminal size={14} />
            Live demo · sample data
          </div>
          <h2 className="mt-2 text-lg font-semibold tracking-tight text-white">
            This is a preview. Run it on your own AWS in 3 commands.
          </h2>
          <p className="mt-1 flex items-center gap-1.5 text-sm leading-relaxed text-gray-400">
            <Lock size={13} className="shrink-0 text-emerald-400/70" />
            100% local · read-only IAM · your credentials never leave your machine.
          </p>
          <a
            href={REPO}
            target="_blank"
            rel="noreferrer"
            className="mt-3 inline-flex items-center gap-2 rounded-lg border border-white/15 bg-white/[0.04] px-3.5 py-2 text-sm font-medium text-white transition hover:bg-white/[0.08]"
          >
            <Github size={15} />
            View on GitHub
          </a>
        </div>

        <div className="w-full space-y-2 lg:max-w-md">
          {STEPS.map((s) => (
            <div key={s.label}>
              <div className="mb-1 text-[11px] font-medium text-gray-500">{s.label}</div>
              <div className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-black/30 px-3 py-2">
                <code className="overflow-x-auto whitespace-nowrap font-mono text-xs text-emerald-200/90">
                  {s.cmd}
                </code>
                <div className="shrink-0">
                  <CopyButton text={s.cmd} label="Copy" />
                </div>
              </div>
            </div>
          ))}
          <p className="pt-1 text-[11px] text-gray-500">
            No AWS handy? Try <code className="text-gray-400">awsco scan --demo-data</code> for this
            sample, or <code className="text-gray-400">awsco serve</code> for this dashboard.
          </p>
        </div>
      </div>
    </div>
  );
}
