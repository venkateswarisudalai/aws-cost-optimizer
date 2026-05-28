"use client";

import { Radar } from "lucide-react";
import { useEffect, useState } from "react";

const PHASES = [
  "Authenticating with AWS…",
  "Listing resources across regions…",
  "Checking EBS volumes & snapshots…",
  "Inspecting NAT gateways & EIPs…",
  "Measuring RDS & load balancer usage…",
  "Pricing findings…",
];

export function ScanningOverlay({ regionCount }: { regionCount: number }) {
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    const id = setInterval(
      () => setPhase((p) => Math.min(p + 1, PHASES.length - 1)),
      1400,
    );
    return () => clearInterval(id);
  }, []);

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="flex w-full max-w-sm flex-col items-center rounded-2xl border border-white/10 bg-gray-950 px-8 py-10 text-center shadow-2xl ring-1 ring-white/5">
        <div className="relative mb-6 flex h-16 w-16 items-center justify-center">
          <span className="absolute inset-0 animate-ping rounded-full bg-emerald-500/20" />
          <span className="absolute inset-0 rounded-full border border-emerald-500/30" />
          <Radar size={28} className="animate-spin text-emerald-400 [animation-duration:3s]" />
        </div>
        <h3 className="text-base font-semibold tracking-tight text-white">
          Scanning your account
        </h3>
        <p className="mt-1 text-xs text-gray-500">
          {regionCount > 0
            ? `Across ${regionCount} region${regionCount === 1 ? "" : "s"}`
            : "Across all enabled regions"}{" "}
          · read-only
        </p>
        <p className="mt-5 h-5 text-sm text-emerald-300 transition-all">
          {PHASES[phase]}
        </p>
      </div>
    </div>
  );
}
