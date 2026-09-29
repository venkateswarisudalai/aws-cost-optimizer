import type { RiskLevel } from "../lib/types";

const styles: Record<RiskLevel, { label: string; cls: string; title: string }> = {
  safe: {
    label: "Safe",
    cls: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
    title: "No downtime or data loss, and easy to reverse",
  },
  restart: {
    label: "Needs restart",
    cls: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
    title: "Brief downtime or a behaviour change, but reversible",
  },
  destructive: {
    label: "Deletes data",
    cls: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
    title: "Deletes data or something that can't be recreated as-is",
  },
  commitment: {
    label: "Commitment",
    cls: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
    title: "A 1–3 year financial commitment",
  },
  info: {
    label: "Investigate",
    cls: "bg-gray-500/15 text-gray-300 ring-gray-500/30",
    title: "Nothing to apply; look into it",
  },
};

export function RiskBadge({ level }: { level: RiskLevel }) {
  const s = styles[level] ?? styles.info;
  return (
    <span
      title={s.title}
      className={`inline-flex items-center whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${s.cls}`}
    >
      {s.label}
    </span>
  );
}
