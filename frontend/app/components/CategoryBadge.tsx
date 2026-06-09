import type { Category } from "../lib/types";

const meta: Record<Category, { label: string; cls: string }> = {
  waste: {
    label: "waste",
    cls: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  },
  rightsizing: {
    label: "rightsizing",
    cls: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  },
  commitment: {
    label: "commitment",
    cls: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  },
  anomaly: {
    label: "anomaly",
    cls: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  },
};

export function CategoryBadge({ category }: { category?: Category }) {
  const m = meta[category ?? "waste"];
  return (
    <span
      className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ring-inset ${m.cls}`}
    >
      {m.label}
    </span>
  );
}
