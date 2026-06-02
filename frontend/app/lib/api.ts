import type {
  AwsCredentials,
  RegionInfo,
  ScanResult,
  ValidateResult,
} from "./types";

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
}): Promise<ScanResult> {
  const body: Record<string, unknown> = {};
  if (opts?.profile) body.profile = opts.profile;
  if (opts?.regions?.length) body.regions = opts.regions;
  if (opts?.credentials) body.credentials = opts.credentials;
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
  return request("/healthz");
}

export async function listProfiles(): Promise<{ profiles: string[]; demo: boolean }> {
  return request("/aws/profiles");
}

/** Full region catalog for the account (or the demo catalog), independent of
 *  any scan. Used to populate the dashboard's region switcher. */
export async function listRegions(
  profile?: string | null,
): Promise<{ regions: RegionInfo[]; demo: boolean }> {
  const qs = profile ? `?profile=${encodeURIComponent(profile)}` : "";
  return request(`/aws/regions${qs}`);
}

/** Verify a connection (profile OR pasted keys) and get account id + regions. */
export async function validateConnection(input: {
  profile?: string | null;
  credentials?: AwsCredentials | null;
}): Promise<ValidateResult> {
  const body: Record<string, unknown> = {};
  if (input.profile) body.profile = input.profile;
  if (input.credentials) body.credentials = input.credentials;
  return request<ValidateResult>("/aws/validate", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
