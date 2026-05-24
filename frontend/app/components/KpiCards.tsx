import { Card, Metric, Text } from "@tremor/react";
import type { ScanResult } from "../lib/types";

function fmtMoney(usd: number): string {
  return usd.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
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
    0
  );
  const highSeverity = scan.findings.filter((f) => f.severity === "high").length;

  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
      <Card decoration="top" decorationColor="emerald">
        <Text>Monthly waste found</Text>
        <Metric className="text-emerald-400">{fmtMoney(totalSavings)}</Metric>
        <Text className="mt-1 text-xs">≈ {fmtMoney(totalSavings * 12)} / yr</Text>
      </Card>
      <Card decoration="top" decorationColor="blue">
        <Text>Findings</Text>
        <Metric>{scan.findings.length}</Metric>
        <Text className="mt-1 text-xs">
          {highSeverity} high · {scan.findings.length - highSeverity} other
        </Text>
      </Card>
      <Card decoration="top" decorationColor="indigo">
        <Text>Regions scanned</Text>
        <Metric>{scan.regions_scanned.length}</Metric>
        <Text className="mt-1 text-xs truncate">
          {scan.regions_scanned.slice(0, 3).join(", ")}
          {scan.regions_scanned.length > 3 ? "…" : ""}
        </Text>
      </Card>
      <Card decoration="top" decorationColor="violet">
        <Text>Last scan</Text>
        <Metric>{fmtAge(scan.finished_at ?? scan.started_at)}</Metric>
        <Text className="mt-1 text-xs">Account {scan.account_id ?? "—"}</Text>
      </Card>
    </div>
  );
}
