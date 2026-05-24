"use client";

import { Card, DonutChart, Legend, Title } from "@tremor/react";
import type { ScanResult } from "../lib/types";

const SERVICE_LABELS: Record<string, string> = {
  ec2: "EC2 / EBS / EIP / NAT",
  rds: "RDS",
  elb: "Load balancers",
  logs: "CloudWatch Logs",
  s3: "S3",
};

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

  return (
    <Card>
      <Title>Waste by service</Title>
      <DonutChart
        className="mt-6 h-64"
        data={data}
        index="name"
        category="savings"
        valueFormatter={(n) =>
          n.toLocaleString("en-US", {
            style: "currency",
            currency: "USD",
            maximumFractionDigits: 0,
          })
        }
        colors={["emerald", "blue", "violet", "amber", "rose", "cyan"]}
      />
      <Legend
        className="mt-4"
        categories={data.map((d) => d.name)}
        colors={["emerald", "blue", "violet", "amber", "rose", "cyan"]}
      />
    </Card>
  );
}
