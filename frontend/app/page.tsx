"use client";

import { Callout } from "@tremor/react";
import { AlertCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { EmptyState } from "./components/EmptyState";
import { FindingsTable } from "./components/FindingsTable";
import { Header } from "./components/Header";
import { KpiCards } from "./components/KpiCards";
import { WasteByService } from "./components/WasteByService";
import { healthz, latestScan, runScan } from "./lib/api";
import type { ScanResult } from "./lib/types";

export default function Dashboard() {
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [scanning, setScanning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isDemo, setIsDemo] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const health = await healthz();
        setIsDemo(health.demo);
        const latest = await latestScan();
        setScan(latest);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function onScan() {
    setScanning(true);
    setError(null);
    try {
      const result = await runScan();
      setScan(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setScanning(false);
    }
  }

  return (
    <>
      <Header onScan={onScan} scanning={scanning} isDemo={isDemo} />
      <main className="max-w-7xl mx-auto px-6 py-8 space-y-6">
        {error && (
          <Callout title="Scan error" icon={AlertCircle} color="rose">
            {error}
          </Callout>
        )}

        {loading ? (
          <div className="text-gray-500 text-sm">Loading…</div>
        ) : scan && scan.findings.length > 0 ? (
          <>
            <KpiCards scan={scan} />
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="lg:col-span-1">
                <WasteByService scan={scan} />
              </div>
              <div className="lg:col-span-2">
                <FindingsTable scan={scan} />
              </div>
            </div>
            {scan.errors.length > 0 && (
              <Callout
                title={`${scan.errors.length} collector(s) had issues`}
                color="amber"
                icon={AlertCircle}
              >
                <ul className="mt-2 text-xs space-y-1 font-mono">
                  {scan.errors.slice(0, 5).map((e, i) => (
                    <li key={i}>
                      {e.collector} @ {e.region}: {e.error}
                    </li>
                  ))}
                </ul>
              </Callout>
            )}
          </>
        ) : (
          <EmptyState onScan={onScan} scanning={scanning} />
        )}
      </main>
    </>
  );
}
