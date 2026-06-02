"use client";

import { AlertCircle, Plug, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { ConnectModal, type ConnectSelection } from "./components/ConnectModal";
import { EmptyState } from "./components/EmptyState";
import { FindingsTable } from "./components/FindingsTable";
import { Header } from "./components/Header";
import { KpiCards } from "./components/KpiCards";
import { RegionSwitcher } from "./components/RegionSwitcher";
import { SavingsByRegion } from "./components/SavingsByRegion";
import { ScanningOverlay } from "./components/ScanningOverlay";
import { WasteByService } from "./components/WasteByService";
import { healthz, latestScan, listRegions, runScan } from "./lib/api";
import { regionName } from "./lib/regions";
import type { ScanResult } from "./lib/types";

const STORAGE_KEY = "awsco.connection";

export default function Dashboard() {
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [scanning, setScanning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isDemo, setIsDemo] = useState(false);
  const [connection, setConnection] = useState<ConnectSelection | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  // "all" or a single region name. Driving the live per-region re-scan.
  const [selectedRegion, setSelectedRegion] = useState<string>("all");
  // The full set of regions available to switch between. Captured from the
  // connection (real accounts) or from a full scan (demo), and never shrunk
  // when the view is scoped to a single region.
  const [allRegions, setAllRegions] = useState<string[]>([]);

  useEffect(() => {
    void (async () => {
      try {
        const health = await healthz();
        setIsDemo(health.demo);
        let profile: string | null = null;
        let storedEnabled: string[] = [];
        if (!health.demo && typeof window !== "undefined") {
          const raw = window.localStorage.getItem(STORAGE_KEY);
          if (raw) {
            try {
              // Only profile-mode connections are ever persisted (no secrets).
              const conn: ConnectSelection = JSON.parse(raw);
              setConnection(conn);
              profile = conn.profile ?? null;
              storedEnabled = conn.enabledRegions ?? conn.regions ?? [];
              if (storedEnabled.length) setAllRegions(storedEnabled);
            } catch {
              /* ignore */
            }
          }
        }
        // The switcher universe is the account's full region catalog — fetched
        // independently so it never collapses to whatever scan is persisted.
        try {
          const rg = await listRegions(profile);
          const enabled = rg.regions.filter((r) => r.enabled).map((r) => r.name);
          if (enabled.length) setAllRegions(enabled);
        } catch {
          /* keep storedEnabled / fall back to the scan's regions below */
        }
        const latest = await latestScan();
        setScan(latest);
        if (latest?.regions_scanned?.length) {
          setAllRegions((cur) => (cur.length ? cur : latest.regions_scanned));
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // Regions to offer in the switcher: the account's full region catalog.
  const availableRegions = connection?.regions?.length
    ? connection.regions
    : allRegions;

  async function doScan(opts?: { sel?: ConnectSelection | null; region?: string }) {
    const sel = opts?.sel ?? connection;
    const region = opts?.region ?? selectedRegion;
    setScanning(true);
    setError(null);
    try {
      // "All regions" scans the regions you chose to monitor (the connect
      // selection); a single pick scans just that one region, live.
      const universe = sel?.regions?.length ? sel.regions : allRegions;
      const regions =
        region === "all" ? (universe.length ? universe : undefined) : [region];
      const result = await runScan({
        profile: sel?.profile,
        regions,
        credentials: sel?.credentials,
      });
      setScan(result);
      // Note: we never reset `allRegions` from a scan — the switcher universe
      // is the account's full catalog (set on load / connect), not just the
      // regions that happened to return findings.
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setScanning(false);
    }
  }

  function onScan() {
    if (isDemo) return void doScan({ region: selectedRegion });
    if (!connection) return setModalOpen(true);
    // Keys-mode connections aren't persisted; if creds were lost (reload),
    // re-open the dialog instead of failing the scan.
    if (connection.mode === "keys" && !connection.credentials) {
      return setModalOpen(true);
    }
    void doScan({ region: selectedRegion });
  }

  function onRegionChange(region: string) {
    if (region === selectedRegion || scanning) return;
    setSelectedRegion(region);
    if (isDemo) return void doScan({ region });
    if (connection?.mode === "keys" && !connection.credentials) {
      return setModalOpen(true);
    }
    void doScan({ region });
  }

  function onConnectConfirm(sel: ConnectSelection) {
    setModalOpen(false);
    setConnection(sel);
    setSelectedRegion("all");
    setAllRegions(sel.regions);
    if (typeof window !== "undefined") {
      if (sel.mode === "profile") {
        window.localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({
            mode: "profile",
            profile: sel.profile,
            regions: sel.regions,
            enabledRegions: sel.enabledRegions,
            accountId: sel.accountId,
          }),
        );
      } else {
        window.localStorage.removeItem(STORAGE_KEY); // never persist keys
      }
    }
    void doScan({ sel, region: "all" });
  }

  const showConnectPrompt =
    !loading && !isDemo && !connection && (!scan || scan.findings.length === 0);

  const connectionLabel = isDemo
    ? null
    : connection
      ? connection.mode === "profile"
        ? connection.profile
        : connection.accountId
          ? `acct ${connection.accountId}`
          : "access keys"
      : null;

  const showDashboard = !loading && !showConnectPrompt && scan;
  const hasFindings = !!scan && scan.findings.length > 0;
  const scanRegionCount =
    selectedRegion === "all" ? availableRegions.length : 1;

  return (
    <>
      <Header
        onScan={onScan}
        onConnect={() => setModalOpen(true)}
        scanning={scanning}
        isDemo={isDemo}
        connectionLabel={connectionLabel}
        regionCount={connection?.regions.length ?? 0}
      />
      <main className="mx-auto max-w-7xl space-y-6 px-6 py-8">
        {error && (
          <div className="flex items-start gap-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
            <AlertCircle size={18} className="mt-0.5 shrink-0" />
            <div>
              <p className="font-medium">Scan error</p>
              <p className="mt-0.5 text-rose-300/80">{error}</p>
            </div>
          </div>
        )}

        {loading ? (
          <LoadingState />
        ) : showConnectPrompt ? (
          <ConnectPrompt onConnect={() => setModalOpen(true)} />
        ) : showDashboard ? (
          <>
            {availableRegions.length > 0 && (
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-3">
                  <RegionSwitcher
                    regions={availableRegions}
                    value={selectedRegion}
                    onChange={onRegionChange}
                    scanning={scanning}
                  />
                  <p className="text-xs text-gray-500">
                    {selectedRegion === "all"
                      ? `Account total across ${scan.regions_scanned.length} region${scan.regions_scanned.length === 1 ? "" : "s"}.`
                      : `Scoped to ${selectedRegion} · ${regionName(selectedRegion)} — switch to All regions for the account total.`}
                  </p>
                </div>
              </div>
            )}

            {hasFindings ? (
              <>
                <KpiCards scan={scan} selectedRegion={selectedRegion} />
                <CrossVerifyNote />
                <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
                  <div className="space-y-6 lg:col-span-1">
                    <WasteByService scan={scan} />
                    <SavingsByRegion
                      scan={scan}
                      selectedRegion={selectedRegion}
                      onSelectRegion={onRegionChange}
                    />
                  </div>
                  <div className="lg:col-span-2">
                    <FindingsTable scan={scan} />
                  </div>
                </div>
                {scan.errors.length > 0 && (
                  <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
                    <p className="font-medium">
                      {scan.errors.length} collector(s) had issues
                    </p>
                    <ul className="mt-2 space-y-1 font-mono text-xs text-amber-300/80">
                      {scan.errors.slice(0, 5).map((e, i) => (
                        <li key={i}>
                          {e.collector} @ {e.region}: {e.error}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            ) : (
              <EmptyState onScan={onScan} scanning={scanning} />
            )}
          </>
        ) : (
          <EmptyState onScan={onScan} scanning={scanning} />
        )}
      </main>

      {scanning && <ScanningOverlay regionCount={scanRegionCount} />}

      <ConnectModal
        open={modalOpen}
        initial={connection}
        onCancel={() => setModalOpen(false)}
        onConfirm={onConnectConfirm}
      />
    </>
  );
}

function CrossVerifyNote() {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-amber-500/25 bg-amber-500/[0.07] px-4 py-3 text-sm text-amber-200/90">
      <ShieldAlert size={18} className="mt-0.5 shrink-0 text-amber-400" />
      <div>
        <p className="font-medium text-amber-200">Cross-verify before you act</p>
        <p className="mt-0.5 leading-relaxed text-amber-200/75">
          Savings are estimates from public on-demand pricing and usage
          heuristics — your actual bill, reserved/savings-plan coverage, and
          resource ownership may differ. Confirm each resource in the AWS
          console before deleting anything, especially fixes flagged as
          destructive.
        </p>
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="h-28 animate-pulse rounded-xl border border-white/5 bg-white/[0.02]"
        />
      ))}
    </div>
  );
}

function ConnectPrompt({ onConnect }: { onConnect: () => void }) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02] px-8 py-16 text-center">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-emerald-500/10 to-transparent" />
      <div className="relative">
        <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500 to-blue-600 shadow-xl shadow-emerald-500/20">
          <Plug size={26} className="text-white" />
        </div>
        <h2 className="text-2xl font-semibold tracking-tight text-white">
          Connect your AWS account
        </h2>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-gray-400">
          Pick a local profile or paste access keys, choose your regions, and
          scan for wasted spend. Your credentials never leave this machine.
        </p>
        <button
          onClick={onConnect}
          className="mt-7 inline-flex items-center gap-2 rounded-lg bg-gradient-to-br from-emerald-500 to-emerald-600 px-5 py-2.5 text-sm font-medium text-white shadow-lg shadow-emerald-500/20 transition hover:from-emerald-400 hover:to-emerald-500"
        >
          <Plug size={16} />
          Connect AWS account
        </button>
        <p className="mt-6 text-xs text-gray-600">
          No AWS yet? Restart with{" "}
          <code className="rounded bg-white/5 px-1.5 py-0.5 text-gray-400">
            awsco serve --demo-data
          </code>{" "}
          to preview the UI.
        </p>
      </div>
    </div>
  );
}
