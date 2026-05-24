import type { ScanResult } from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ??
  (typeof window !== "undefined" ? "" : "http://localhost:3000");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${text}`);
  }
  return resp.json() as Promise<T>;
}

export async function latestScan(): Promise<ScanResult | null> {
  try {
    return await request<ScanResult>("/scans/latest");
  } catch (err) {
    if (err instanceof Error && err.message.startsWith("404")) return null;
    throw err;
  }
}

export async function runScan(): Promise<ScanResult> {
  return request<ScanResult>("/scan", { method: "POST" });
}

export async function healthz(): Promise<{
  ok: boolean;
  version: string;
  demo: boolean;
}> {
  return request("/healthz");
}
