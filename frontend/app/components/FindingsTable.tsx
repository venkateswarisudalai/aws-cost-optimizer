"use client";

import {
  Card,
  Select,
  SelectItem,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
  Text,
  TextInput,
  Title,
} from "@tremor/react";
import { AlertTriangle, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { Finding, ScanResult } from "../lib/types";
import { CopyButton } from "./CopyButton";
import { SeverityBadge } from "./SeverityBadge";

function fmtMoney(n: number): string {
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function FindingsTable({ scan }: { scan: ScanResult }) {
  const [severity, setSeverity] = useState<string>("all");
  const [region, setRegion] = useState<string>("all");
  const [q, setQ] = useState("");

  const allRegions = useMemo(
    () => Array.from(new Set(scan.findings.map((f) => f.region))).sort(),
    [scan]
  );

  const filtered = useMemo(() => {
    return scan.findings.filter((f) => {
      if (severity !== "all" && f.severity !== severity) return false;
      if (region !== "all" && f.region !== region) return false;
      if (
        q &&
        !`${f.title} ${f.check_id} ${f.resource_id}`
          .toLowerCase()
          .includes(q.toLowerCase())
      )
        return false;
      return true;
    });
  }, [scan, severity, region, q]);

  return (
    <Card>
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-4">
        <div>
          <Title>Findings</Title>
          <Text className="text-xs">
            Sorted by monthly savings. Click "Copy fix" to grab the `aws` CLI
            command.
          </Text>
        </div>
        <div className="flex gap-2 flex-wrap">
          <TextInput
            icon={Search}
            placeholder="Search title, check, resource…"
            value={q}
            onValueChange={setQ}
            className="w-60"
          />
          <Select
            value={severity}
            onValueChange={setSeverity}
            className="w-32"
          >
            <SelectItem value="all">All severities</SelectItem>
            <SelectItem value="high">High</SelectItem>
            <SelectItem value="medium">Medium</SelectItem>
            <SelectItem value="low">Low</SelectItem>
          </Select>
          <Select value={region} onValueChange={setRegion} className="w-36">
            <SelectItem value="all">All regions</SelectItem>
            {allRegions.map((r) => (
              <SelectItem key={r} value={r}>
                {r}
              </SelectItem>
            ))}
          </Select>
        </div>
      </div>

      <Table className="mt-2">
        <TableHead>
          <TableRow>
            <TableHeaderCell>Sev</TableHeaderCell>
            <TableHeaderCell className="text-right">$ / mo</TableHeaderCell>
            <TableHeaderCell>Finding</TableHeaderCell>
            <TableHeaderCell>Region</TableHeaderCell>
            <TableHeaderCell>Check</TableHeaderCell>
            <TableHeaderCell>Fix</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {filtered.map((f) => (
            <FindingRow key={f.id} f={f} />
          ))}
          {filtered.length === 0 && (
            <TableRow>
              <TableCell colSpan={6}>
                <Text className="text-center py-4">
                  No findings match the current filters.
                </Text>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </Card>
  );
}

function FindingRow({ f }: { f: Finding }) {
  return (
    <TableRow>
      <TableCell>
        <SeverityBadge severity={f.severity} />
      </TableCell>
      <TableCell className="text-right font-medium text-emerald-400">
        {fmtMoney(f.monthly_savings_usd)}
      </TableCell>
      <TableCell>
        <div className="flex flex-col">
          <span className="font-medium">{f.title}</span>
          <span className="text-xs text-gray-500 truncate max-w-md">
            {f.description}
          </span>
          {f.fix_destructive && (
            <span className="mt-1 inline-flex items-center gap-1 text-xs text-amber-400">
              <AlertTriangle size={10} />
              Fix deletes data — verify before running
            </span>
          )}
        </div>
      </TableCell>
      <TableCell className="font-mono text-xs">{f.region}</TableCell>
      <TableCell className="font-mono text-xs text-gray-400">
        {f.check_id}
      </TableCell>
      <TableCell>
        <CopyButton text={f.cli_fix_command} />
      </TableCell>
    </TableRow>
  );
}
