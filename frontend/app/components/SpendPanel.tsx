import { Receipt } from "lucide-react";
import { countedSavings } from "../lib/savings";
import type { ScanResult } from "../lib/types";

function fmtMoney(usd: number): string {
  return usd.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

/** What the account actually spends (Cost Explorer), with the scan's savings
 *  read against it — the "how low can this bill go?" view. */
export function SpendPanel({ scan }: { scan: ScanResult }) {
  const spend = scan.spend;
  if (!spend) {
    return (
      <section className="rounded-2xl border border-white/10 bg-white/[0.02] px-5 py-4 text-sm text-gray-400">
        <div className="flex items-center gap-2 font-medium text-gray-300">
          <Receipt size={15} /> Spend baseline unavailable
        </div>
        <p className="mt-1 text-xs text-gray-500">
          Grant <code className="text-gray-300">ce:GetCostAndUsage</code> and{" "}
          <code className="text-gray-300">ce:GetCostForecast</code> (see
          infra/iam-policy.json) to see where the money goes and how far the bill
          can drop.
        </p>
      </section>
    );
  }

  const savings = scan.findings.reduce((a, f) => a + countedSavings(f), 0);
  const monthly = spend.forecast_month_usd ?? spend.total_30d_usd;
  const after = Math.max(0, monthly - savings);
  const pct = monthly > 0 ? Math.min(100, (savings / monthly) * 100) : 0;
  const max = Math.max(...spend.by_service.map((s) => s.cost_usd), 1);

  return (
    <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-gray-200">
          <Receipt size={15} /> Where the money goes
          <span className="font-normal text-gray-500">
            last 30 days · {spend.period_start} → {spend.period_end}
          </span>
        </h2>
        <span className="text-xs text-gray-500">source: Cost Explorer</span>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Last 30 days" value={fmtMoney(spend.total_30d_usd)} />
        <Stat
          label="Month to date"
          value={spend.month_to_date_usd == null ? "—" : fmtMoney(spend.month_to_date_usd)}
        />
        <Stat
          label="Forecast this month"
          value={spend.forecast_month_usd == null ? "—" : fmtMoney(spend.forecast_month_usd)}
        />
        <Stat
          label="After fixes"
          value={`${fmtMoney(after)}/mo`}
          sub={`−${pct.toFixed(0)}% if every finding is applied`}
          accent
        />
      </div>

      <ul className="mt-5 space-y-2">
        {spend.by_service.map((s) => (
          <li key={s.service} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
            <div className="min-w-0">
              <div className="overflow-hidden text-ellipsis whitespace-nowrap text-xs text-gray-300">
                {s.service}
              </div>
              <div className="mt-1 h-1.5 rounded-full bg-white/5">
                <div
                  className="h-1.5 rounded-full bg-blue-400/70"
                  style={{ width: `${(s.cost_usd / max) * 100}%` }}
                />
              </div>
            </div>
            <span className="text-xs tabular-nums text-gray-400">{fmtMoney(s.cost_usd)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Stat({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: boolean;
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2.5">
      <div className="text-[11px] uppercase tracking-wide text-gray-500">{label}</div>
      <div
        className={`mt-1 text-lg font-semibold tabular-nums ${accent ? "text-emerald-400" : "text-white"}`}
      >
        {value}
      </div>
      {sub && <div className="text-[11px] text-gray-500">{sub}</div>}
    </div>
  );
}
