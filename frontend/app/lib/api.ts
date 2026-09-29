import { demoRegions, demoScan } from "./demoData";
import type {
  AwsCredentials,
  Confirmation,
  RegionInfo,
  ScanResult,
  ValidateResult,
} from "./types";

// Hosted showcase build: serve bundled sample data with no backend. Real
// (local) builds leave this unset and talk to the awsco server as usual.
const DEMO = process.env.NEXT_PUBLIC_DEMO === "1";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ??
  (typeof window !== "undefined" ? "" : "http://localhost:3000");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!resp.ok) {
    let detail = "";
    try {
      const data = await resp.json();
      detail = data?.detail ?? JSON.stringify(data);
    } catch {
      detail = await resp.text();
    }
    throw new Error(detail || `${resp.status} ${resp.statusText}`);
  }
  return resp.json() as Promise<T>;
}

export async function latestScan(): Promise<ScanResult | null> {
  if (DEMO) return demoScan();
  try {
    return await request<ScanResult>("/scans/latest");
  } catch (err) {
    if (err instanceof Error && err.message.toLowerCase().includes("no scans"))
      return null;
    // 404 with no body falls through to the generic message; treat as empty.
    if (err instanceof Error && err.message.startsWith("404")) return null;
    throw err;
  }
}

export async function runScan(opts?: {
  profile?: string | null;
  regions?: string[] | null;
  credentials?: AwsCredentials | null;
  expectedAccountId?: string | null;
  lookbackDays?: number;
}): Promise<ScanResult> {
  if (DEMO) return demoScan(opts?.regions ?? null);
  const body: Record<string, unknown> = {};
  if (opts?.profile) body.profile = opts.profile;
  if (opts?.regions?.length) body.regions = opts.regions;
  if (opts?.credentials) body.credentials = opts.credentials;
  if (opts?.expectedAccountId) body.expected_account_id = opts.expectedAccountId;
  if (opts?.lookbackDays) body.lookback_days = opts.lookbackDays;
  return request<ScanResult>("/scan", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function healthz(): Promise<{
  ok: boolean;
  version: string;
  demo: boolean;
}> {
  if (DEMO) return { ok: true, version: "demo", demo: true };
  return request("/healthz");
}

export async function listProfiles(): Promise<{ profiles: string[]; demo: boolean }> {
  if (DEMO) return { profiles: ["demo"], demo: true };
  return request("/aws/profiles");
}

/** Full region catalog for the account (or the demo catalog), independent of
 *  any scan. Used to populate the dashboard's region switcher. */
export async function listRegions(
  profile?: string | null,
): Promise<{ regions: RegionInfo[]; demo: boolean }> {
  if (DEMO) return { regions: demoRegions, demo: true };
  const qs = profile ? `?profile=${encodeURIComponent(profile)}` : "";
  return request(`/aws/regions${qs}`);
}

/** Verify a connection (profile OR pasted keys) and get account id + regions. */
export async function validateConnection(input: {
  profile?: string | null;
  credentials?: AwsCredentials | null;
  expectedAccountId?: string | null;
}): Promise<ValidateResult> {
  if (DEMO) {
    return {
      account_id: "123456789012",
      arn: "arn:aws:iam::123456789012:user/demo",
      regions: demoRegions,
      warnings: [],
      demo: true,
    };
  }
  const body: Record<string, unknown> = {};
  if (input.profile) body.profile = input.profile;
  if (input.credentials) body.credentials = input.credentials;
  if (input.expectedAccountId) body.expected_account_id = input.expectedAccountId;
  return request<ValidateResult>("/aws/validate", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// --- Slack owner confirmations ---------------------------------------------

export interface AskOwnerResult {
  sent: boolean;
  simulated: boolean;
  reason: string | null;
  message: { text: string };
}

// The hosted demo has no backend; keep asks in memory so the flow still works.
const demoAsks = new Map<string, Confirmation>();

export async function askOwner(findingId: string): Promise<AskOwnerResult> {
  if (DEMO) {
    const f = demoScan().findings.find((x) => x.id === findingId);
    demoAsks.set(findingId, {
      finding_id: findingId,
      resource_id: f?.resource_id ?? findingId,
      owner_name: f?.owner?.name ?? null,
      channel: "demo",
      status: "pending",
      responder: null,
      note: null,
      asked_at: new Date().toISOString(),
      answered_at: null,
    });
    return {
      sent: false,
      simulated: true,
      reason: "demo mode",
      message: { text: `Is this still needed? ${f?.title ?? findingId}` },
    };
  }
  return request<AskOwnerResult>(`/findings/${encodeURIComponent(findingId)}/ask-owner`, {
    method: "POST",
    body: "{}",
  });
}

export async function listConfirmations(): Promise<Confirmation[]> {
  if (DEMO) return Array.from(demoAsks.values());
  return (await request<{ confirmations: Confirmation[] }>("/confirmations")).confirmations;
}

export async function syncConfirmations(): Promise<{
  updated: number;
  errors: string[];
  confirmations: Confirmation[];
}> {
  if (DEMO) {
    let updated = 0;
    for (const c of demoAsks.values()) {
      if (c.status === "pending") {
        Object.assign(c, {
          status: "delete_ok",
          responder: "demo-teammate",
          note: "(demo) Left over from the 2024 migration, fine to remove.",
          answered_at: new Date().toISOString(),
        });
        updated++;
      }
    }
    return { updated, errors: [], confirmations: Array.from(demoAsks.values()) };
  }
  return request("/confirmations/sync", { method: "POST", body: "{}" });
}
