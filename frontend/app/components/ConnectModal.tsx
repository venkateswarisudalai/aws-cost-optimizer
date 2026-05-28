"use client";

import {
  ArrowLeft,
  ArrowRight,
  Check,
  KeyRound,
  Loader2,
  Search,
  ShieldCheck,
  UserCircle2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { listProfiles, validateConnection } from "../lib/api";
import type { AwsCredentials, RegionInfo } from "../lib/types";

export interface ConnectSelection {
  mode: "profile" | "keys";
  profile: string | null;
  credentials: AwsCredentials | null; // in-memory only — never persisted
  regions: string[];
  accountId: string | null;
  arn?: string | null;
}

interface Props {
  open: boolean;
  initial?: ConnectSelection | null;
  onCancel: () => void;
  onConfirm: (sel: ConnectSelection) => void;
}

type Mode = "profile" | "keys";
type Step = "connect" | "regions";

export function ConnectModal({ open, initial, onCancel, onConfirm }: Props) {
  const [step, setStep] = useState<Step>("connect");
  const [mode, setMode] = useState<Mode>(initial?.mode ?? "profile");

  // profile mode
  const [profiles, setProfiles] = useState<string[]>([]);
  const [profile, setProfile] = useState<string | null>(initial?.profile ?? null);

  // keys mode
  const [accessKeyId, setAccessKeyId] = useState("");
  const [secretAccessKey, setSecretAccessKey] = useState("");
  const [sessionToken, setSessionToken] = useState("");
  const [showSecret, setShowSecret] = useState(false);

  // validation result + region selection
  const [accountId, setAccountId] = useState<string | null>(null);
  const [arn, setArn] = useState<string | null>(null);
  const [regions, setRegions] = useState<RegionInfo[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [regionFilter, setRegionFilter] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset to a clean state each time the dialog opens.
  useEffect(() => {
    if (!open) return;
    setStep("connect");
    setMode(initial?.mode ?? "profile");
    setProfile(initial?.profile ?? null);
    setAccessKeyId("");
    setSecretAccessKey("");
    setSessionToken("");
    setShowSecret(false);
    setAccountId(null);
    setArn(null);
    setRegions([]);
    setSelected(new Set(initial?.regions ?? []));
    setRegionFilter("");
    setError(null);
    setBusy(true);
    listProfiles()
      .then((r) => {
        setProfiles(r.profiles);
        setProfile((cur) => cur ?? (r.profiles[0] ?? null));
      })
      .catch(() => setProfiles([]))
      .finally(() => setBusy(false));
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const credentials = useMemo<AwsCredentials | null>(() => {
    if (mode !== "keys") return null;
    if (!accessKeyId.trim() || !secretAccessKey.trim()) return null;
    return {
      access_key_id: accessKeyId.trim(),
      secret_access_key: secretAccessKey.trim(),
      session_token: sessionToken.trim() || null,
    };
  }, [mode, accessKeyId, secretAccessKey, sessionToken]);

  const canTest =
    !busy &&
    (mode === "profile" ? !!profile : !!credentials);

  async function test() {
    setBusy(true);
    setError(null);
    try {
      const res = await validateConnection({
        profile: mode === "profile" ? profile : null,
        credentials: mode === "keys" ? credentials : null,
      });
      setAccountId(res.account_id);
      setArn(res.arn);
      setRegions(res.regions);
      // Only activated regions are scannable. Preselect those (or restore the
      // prior selection if it still applies to this account).
      const enabledNames = res.regions.filter((r) => r.enabled).map((r) => r.name);
      const prior = initial?.regions?.filter((n) => enabledNames.includes(n)) ?? [];
      setSelected(new Set(prior.length ? prior : enabledNames));
      setStep("regions");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const enabledCount = useMemo(
    () => regions.filter((r) => r.enabled).length,
    [regions],
  );
  const filteredRegions = useMemo(
    () =>
      regions.filter((r) =>
        r.name.toLowerCase().includes(regionFilter.toLowerCase()),
      ),
    [regions, regionFilter],
  );

  function toggle(region: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(region) ? next.delete(region) : next.add(region);
      return next;
    });
  }

  function confirm() {
    onConfirm({
      mode,
      profile: mode === "profile" ? profile : null,
      credentials: mode === "keys" ? credentials : null,
      regions: Array.from(selected),
      accountId,
      arn,
    });
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-[fadeIn_120ms_ease-out]"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-2xl border border-white/10 bg-gray-950 shadow-2xl shadow-black/50 ring-1 ring-white/5"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="relative border-b border-white/10 px-6 py-5">
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-emerald-500/10 via-transparent to-blue-500/10" />
          <div className="relative flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-500 to-blue-600 shadow-lg shadow-emerald-500/20">
                <ShieldCheck size={18} className="text-white" />
              </div>
              <div>
                <h2 className="text-base font-semibold tracking-tight text-white">
                  Connect an AWS account
                </h2>
                <p className="text-xs text-gray-400">
                  {step === "connect"
                    ? "Credentials are used locally and never leave this machine."
                    : "Choose which regions to scan."}
                </p>
              </div>
            </div>
            <button
              onClick={onCancel}
              className="rounded-md p-1 text-gray-500 transition-colors hover:bg-white/5 hover:text-gray-200"
              aria-label="Close"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {step === "connect" ? (
          <div className="space-y-5 px-6 py-5">
            {/* Mode toggle */}
            <div className="grid grid-cols-2 gap-1 rounded-lg border border-white/10 bg-white/[0.03] p-1">
              <TabButton
                active={mode === "profile"}
                icon={<UserCircle2 size={15} />}
                label="Local profile"
                onClick={() => {
                  setMode("profile");
                  setError(null);
                }}
              />
              <TabButton
                active={mode === "keys"}
                icon={<KeyRound size={15} />}
                label="Access keys"
                onClick={() => {
                  setMode("keys");
                  setError(null);
                }}
              />
            </div>

            {mode === "profile" ? (
              <div>
                <Label>Profile</Label>
                <select
                  className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2.5 text-sm text-gray-100 outline-none transition focus:border-emerald-500/60 focus:ring-2 focus:ring-emerald-500/20"
                  value={profile ?? ""}
                  onChange={(e) => setProfile(e.target.value || null)}
                  disabled={busy || profiles.length === 0}
                >
                  {profiles.length === 0 && (
                    <option value="">No profiles found in ~/.aws</option>
                  )}
                  {profiles.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
                <Hint>
                  Read from <Mono>~/.aws/credentials</Mono> and{" "}
                  <Mono>~/.aws/config</Mono>. No profile? Switch to{" "}
                  <button
                    className="text-emerald-400 hover:text-emerald-300"
                    onClick={() => setMode("keys")}
                  >
                    Access keys
                  </button>
                  .
                </Hint>
              </div>
            ) : (
              <div className="space-y-3">
                <div>
                  <Label>Access key ID</Label>
                  <Input
                    placeholder="AKIA…"
                    value={accessKeyId}
                    onChange={setAccessKeyId}
                    mono
                  />
                </div>
                <div>
                  <Label>Secret access key</Label>
                  <div className="relative">
                    <Input
                      placeholder="••••••••••••••••••••••••"
                      value={secretAccessKey}
                      onChange={setSecretAccessKey}
                      mono
                      type={showSecret ? "text" : "password"}
                    />
                    <button
                      onClick={() => setShowSecret((s) => !s)}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-gray-500 hover:text-gray-300"
                    >
                      {showSecret ? "Hide" : "Show"}
                    </button>
                  </div>
                </div>
                <div>
                  <Label>
                    Session token{" "}
                    <span className="font-normal text-gray-600">(optional)</span>
                  </Label>
                  <Input
                    placeholder="For temporary / SSO credentials"
                    value={sessionToken}
                    onChange={setSessionToken}
                    mono
                  />
                </div>
                <Hint>
                  Sent only to the local backend on this machine, kept in memory
                  for this session, and never written to disk.
                </Hint>
              </div>
            )}

            {error && <ErrorBox>{error}</ErrorBox>}

            <TrustNote />
          </div>
        ) : (
          <div className="space-y-4 px-6 py-5">
            {/* Identity banner */}
            <div className="flex items-center gap-3 rounded-lg border border-emerald-500/20 bg-emerald-500/[0.06] px-4 py-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-500/15">
                <Check size={16} className="text-emerald-400" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-emerald-300">
                  Connected to account {accountId}
                </p>
                <p className="truncate font-mono text-xs text-gray-500">{arn}</p>
              </div>
            </div>

            <div>
              <div className="flex items-baseline justify-between">
                <Label>
                  Regions{" "}
                  <span className="font-normal normal-case text-gray-500">
                    ({selected.size}/{enabledCount} enabled selected)
                  </span>
                </Label>
                <div className="flex gap-2 text-xs">
                  <button
                    className="text-emerald-400 hover:text-emerald-300 disabled:opacity-40"
                    onClick={() =>
                      setSelected(
                        new Set(
                          regions.filter((r) => r.enabled).map((r) => r.name),
                        ),
                      )
                    }
                    disabled={enabledCount === 0}
                  >
                    Select all
                  </button>
                  <span className="text-gray-700">·</span>
                  <button
                    className="text-gray-400 hover:text-gray-200 disabled:opacity-40"
                    onClick={() => setSelected(new Set())}
                    disabled={selected.size === 0}
                  >
                    Clear
                  </button>
                </div>
              </div>

              <div className="mt-1.5 overflow-hidden rounded-lg border border-white/10 bg-white/[0.03]">
                <div className="flex items-center gap-2 border-b border-white/10 px-3 py-2">
                  <Search size={14} className="text-gray-500" />
                  <input
                    className="flex-1 bg-transparent text-sm text-gray-100 placeholder-gray-600 outline-none"
                    placeholder="Filter regions…"
                    value={regionFilter}
                    onChange={(e) => setRegionFilter(e.target.value)}
                  />
                </div>
                <div className="grid max-h-56 grid-cols-2 gap-1 overflow-y-auto p-2">
                  {filteredRegions.length === 0 ? (
                    <div className="col-span-2 px-2 py-3 text-xs text-gray-500">
                      No regions match.
                    </div>
                  ) : (
                    filteredRegions.map((r) => {
                      if (!r.enabled) {
                        return (
                          <div
                            key={r.name}
                            title="Not activated on this account — enable it in the AWS console to scan it"
                            className="flex cursor-not-allowed items-center gap-2 rounded-md px-2.5 py-1.5 text-sm opacity-50"
                          >
                            <span className="h-4 w-4 shrink-0 rounded border border-gray-700 border-dashed" />
                            <code className="truncate text-xs text-gray-500">
                              {r.name}
                            </code>
                            <span className="ml-auto text-[10px] uppercase tracking-wide text-gray-600">
                              off
                            </span>
                          </div>
                        );
                      }
                      const checked = selected.has(r.name);
                      return (
                        <button
                          key={r.name}
                          onClick={() => toggle(r.name)}
                          className={`flex items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm transition ${
                            checked
                              ? "bg-emerald-500/10 text-gray-100"
                              : "text-gray-300 hover:bg-white/5"
                          }`}
                        >
                          <span
                            className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                              checked
                                ? "border-emerald-500 bg-emerald-500"
                                : "border-gray-600"
                            }`}
                          >
                            {checked && <Check size={11} className="text-white" />}
                          </span>
                          <code className="text-xs">{r.name}</code>
                        </button>
                      );
                    })
                  )}
                </div>
              </div>
              <Hint>
                ⏱ Scanning {selected.size} region{selected.size === 1 ? "" : "s"}{" "}
                takes ~{Math.max(10, selected.size * 4)}s.{" "}
                {regions.length > enabledCount && (
                  <>
                    {regions.length - enabledCount} region
                    {regions.length - enabledCount === 1 ? "" : "s"} not activated
                    on this account (shown as <span className="text-gray-400">off</span>).
                  </>
                )}
              </Hint>
            </div>

            {error && <ErrorBox>{error}</ErrorBox>}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-white/10 px-6 py-4">
          {step === "regions" ? (
            <button
              onClick={() => {
                setStep("connect");
                setError(null);
              }}
              className="inline-flex items-center gap-1.5 text-sm text-gray-400 transition hover:text-gray-200"
            >
              <ArrowLeft size={15} /> Back
            </button>
          ) : (
            <span className="text-xs text-gray-600">Step 1 of 2</span>
          )}

          <div className="flex gap-2">
            <button
              onClick={onCancel}
              className="rounded-lg px-4 py-2 text-sm text-gray-300 transition hover:bg-white/5"
            >
              Cancel
            </button>
            {step === "connect" ? (
              <PrimaryButton onClick={test} disabled={!canTest} busy={busy}>
                {busy ? "Connecting…" : "Test connection"}
                {!busy && <ArrowRight size={15} />}
              </PrimaryButton>
            ) : (
              <PrimaryButton
                onClick={confirm}
                disabled={selected.size === 0 || busy}
                busy={busy}
              >
                Scan {selected.size} region{selected.size === 1 ? "" : "s"}
              </PrimaryButton>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---- small presentational helpers ---- */

function TabButton({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition ${
        active
          ? "bg-white/10 text-white shadow-sm"
          : "text-gray-400 hover:text-gray-200"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-gray-400">
      {children}
    </label>
  );
}

function Input({
  value,
  onChange,
  placeholder,
  mono,
  type = "text",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  mono?: boolean;
  type?: string;
}) {
  return (
    <input
      type={type}
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      spellCheck={false}
      autoComplete="off"
      className={`w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2.5 text-sm text-gray-100 placeholder-gray-600 outline-none transition focus:border-emerald-500/60 focus:ring-2 focus:ring-emerald-500/20 ${
        mono ? "font-mono" : ""
      }`}
    />
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return <p className="mt-1.5 text-xs leading-relaxed text-gray-500">{children}</p>;
}

function Mono({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded bg-white/5 px-1 py-0.5 text-[11px] text-gray-300">
      {children}
    </code>
  );
}

function ErrorBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2.5 text-xs leading-relaxed text-rose-300">
      {children}
    </div>
  );
}

function TrustNote() {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/[0.05] px-3 py-2.5 text-xs leading-relaxed text-emerald-300/90">
      <ShieldCheck size={14} className="mt-0.5 shrink-0 text-emerald-400" />
      <span>
        boto3 reads credentials locally and calls AWS APIs directly. No SaaS, no
        telemetry, no outbound calls except to AWS.
      </span>
    </div>
  );
}

function PrimaryButton({
  children,
  onClick,
  disabled,
  busy,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  busy?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-1.5 rounded-lg bg-gradient-to-br from-emerald-500 to-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-emerald-500/20 transition hover:from-emerald-400 hover:to-emerald-500 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
    >
      {busy && <Loader2 size={15} className="animate-spin" />}
      {children}
    </button>
  );
}
