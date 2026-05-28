import { Clock, MapPin, TrendingDown, Wallet } from "lucide-react";
import type { ScanResult } from "../lib/types";

function fmtMoney(usd: number, maxFrac = 0): string {
  return usd.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: maxFrac,
  });
}

function fmtAge(iso: string | null): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.round(ms / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

export function KpiCards({ scan }: { scan: ScanResult }) {
  const totalSavings = scan.findings.reduce(
    (acc, f) => acc + f.monthly_savings_usd,
    0,
  );
  const high = scan.findings.filter((f) => f.severity === "high").length;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
      {/* Hero */}
      <div className="relative overflow-hidden rounded-2xl border border-emerald-500/20 bg-gradient-to-br from-emerald-500/[0.12] via-emerald-500/[0.04] to-transparent p-6 lg:col-span-6">
        <div className="pointer-events-none absolute -right-8 -top-8 h-40 w-40 rounded-full bg-emerald-500/10 blur-3xl" />
        <div className="relative">
          <div className="flex items-center gap-2 text-sm text-emerald-300/80">
            <Wallet size={16} />
            Monthly waste found
          </div>
          <div className="mt-2 text-5xl font-semibold tracking-tight text-emerald-400">
            {fmtMoney(totalSavings)}
          </div>
          <div className="mt-3 flex items-center gap-1.5 text-sm text-gray-400">
            <TrendingDown size={15} className="text-emerald-400" />
            ≈ {fmtMoney(totalSavings * 12)} / year if left running
          </div>
        </div>
      </div>

      <StatCard
        className="lg:col-span-2"
        label="Findings"
        value={String(scan.findings.length)}
        sub={`${high} high · ${scan.findings.length - high} other`}
      />
      <StatCard
        className="lg:col-span-2"
        icon={<MapPin size={15} />}
        label="Regions"
        value={String(scan.regions_scanned.length)}
        sub={
          scan.regions_scanned.slice(0, 2).join(", ") +
          (scan.regions_scanned.length > 2 ? "…" : "")
        }
      />
      <StatCard
        className="lg:col-span-2"
        icon={<Clock size={15} />}
        label="Last scan"
        value={fmtAge(scan.finished_at ?? scan.started_at)}
        sub={scan.account_id ? `acct ${scan.account_id}` : "—"}
      />
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  icon,
  className = "",
}: {
  label: string;
  value: string;
  sub: string;
  icon?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col justify-between rounded-2xl border border-white/10 bg-white/[0.02] p-5 ${className}`}
    >
      <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-500">
        {icon}
        {label}
      </div>
      <div className="mt-3">
        <div className="text-2xl font-semibold tracking-tight text-white">
          {value}
        </div>
        <div className="mt-0.5 truncate text-xs text-gray-500">{sub}</div>
      </div>
    </div>
  );
}
