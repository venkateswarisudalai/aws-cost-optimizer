"use client";

import { DonutChart } from "@tremor/react";
import { PieChart } from "lucide-react";
import type { ScanResult } from "../lib/types";

const SERVICE_LABELS: Record<string, string> = {
  ec2: "EC2 / EBS / EIP / NAT",
  rds: "RDS",
  elb: "Load balancers",
  logs: "CloudWatch Logs",
  s3: "S3",
};

const COLORS = ["emerald", "blue", "violet", "amber", "rose", "cyan"];
const SWATCH: Record<string, string> = {
  emerald: "bg-emerald-500",
  blue: "bg-blue-500",
  violet: "bg-violet-500",
  amber: "bg-amber-500",
  rose: "bg-rose-500",
  cyan: "bg-cyan-500",
};

function fmtMoney(n: number): string {
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export function WasteByService({ scan }: { scan: ScanResult }) {
  const totals = new Map<string, number>();
  for (const f of scan.findings) {
    totals.set(f.service, (totals.get(f.service) ?? 0) + f.monthly_savings_usd);
  }
  const data = Array.from(totals.entries())
    .map(([service, savings]) => ({
      name: SERVICE_LABELS[service] ?? service,
      savings: Math.round(savings * 100) / 100,
    }))
    .sort((a, b) => b.savings - a.savings);

  const total = data.reduce((a, d) => a + d.savings, 0);

  return (
    <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-5">
      <div className="flex items-center gap-2">
        <PieChart size={16} className="text-gray-400" />
        <h2 className="text-sm font-semibold tracking-tight text-white">
          Waste by service
        </h2>
      </div>

      <DonutChart
        className="mt-6 h-52"
        data={data}
        index="name"
        category="savings"
        valueFormatter={fmtMoney}
        colors={COLORS}
        showLabel={false}
      />

      <div className="mt-5 space-y-2">
        {data.map((d, i) => {
          const color = COLORS[i % COLORS.length];
          const pct = total > 0 ? Math.round((d.savings / total) * 100) : 0;
          return (
            <div key={d.name} className="flex items-center gap-2 text-sm">
              <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${SWATCH[color]}`} />
              <span className="flex-1 truncate text-gray-300">{d.name}</span>
              <span className="tabular-nums text-gray-500">{pct}%</span>
              <span className="w-16 text-right font-medium tabular-nums text-gray-100">
                {fmtMoney(d.savings)}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
