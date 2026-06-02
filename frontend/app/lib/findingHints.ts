import type { Finding } from "./types";

/**
 * A short "how long it's been idle / when it was last used" hint, derived from
 * the evidence each collector already gathers. Returns null when there's
 * nothing meaningful to show, so the UI can fall back to a dash.
 *
 * This is intentionally read-only and best-effort: different checks expose
 * different signals (age in days, a create timestamp, a 7-day usage metric),
 * so we normalise each into one compact label for the findings table.
 */
export function idleHint(f: Finding): string | null {
  const e = f.evidence ?? {};

  const num = (k: string): number | null =>
    typeof e[k] === "number" ? (e[k] as number) : null;

  const daysSince = (iso: unknown): number | null => {
    if (typeof iso !== "string") return null;
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return null;
    return Math.max(0, Math.floor((Date.now() - t) / 86_400_000));
  };

  switch (f.check_id) {
    case "ebs.unattached": {
      const d = daysSince(e.create_time);
      return d != null ? `unattached · ${d}d` : "unattached";
    }
    case "ec2.stopped-billed-ebs": {
      const d = num("days_stopped");
      return d != null ? `stopped · ${d}d` : "stopped";
    }
    case "ebs.snapshot-old": {
      const d = num("age_days") ?? daysSince(e.start_time);
      return d != null ? `${d}d old` : "old snapshot";
    }
    case "nat.idle": {
      const b = num("bytes_out_7d");
      return b != null ? `${fmtBytes(b)} out · 7d` : "idle · 7d";
    }
    case "rds.idle": {
      const c = num("max_connections_7d");
      return c != null ? `${c} conn${c === 1 ? "" : "s"} · 7d` : "idle · 7d";
    }
    case "lb.unused":
      return typeof e.reason === "string" ? (e.reason as string) : "no targets";
    case "eip.unused":
      return "unattached";
    case "logs.no-retention": {
      const gb = num("stored_gb");
      return gb != null ? `${gb} GB · no expiry` : "no expiry";
    }
    case "ebs.gp2-to-gp3":
      return "gp2 → gp3";
    default: {
      const d = daysSince(e.create_time ?? e.created_time ?? e.start_time);
      return d != null ? `${d}d` : null;
    }
  }
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${Math.round(n / 1024)} KB`;
  if (n < 1024 ** 3) return `${Math.round(n / 1024 ** 2)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}
