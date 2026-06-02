"use client";

import { ChevronDown, Globe, MapPin } from "lucide-react";
import { regionLabel } from "../lib/regions";

/**
 * Dashboard-level region selector. Picking a region triggers a fresh, live
 * re-scan scoped to that region; "All regions" re-scans the whole account.
 */
export function RegionSwitcher({
  regions,
  value,
  onChange,
  scanning,
  disabled,
}: {
  regions: string[];
  value: string; // "all" | <region name>
  onChange: (value: string) => void;
  scanning: boolean;
  disabled?: boolean;
}) {
  const isAll = value === "all";
  return (
    <label className="group relative inline-flex items-center">
      <span className="pointer-events-none absolute left-3 text-gray-500 group-focus-within:text-emerald-400">
        {isAll ? <Globe size={14} /> : <MapPin size={14} />}
      </span>
      <select
        value={value}
        disabled={disabled || scanning}
        onChange={(e) => onChange(e.target.value)}
        aria-label="Region to scan"
        className="appearance-none rounded-lg border border-white/10 bg-white/[0.03] py-2 pl-9 pr-9 text-sm font-medium text-gray-100 outline-none transition focus:border-emerald-500/60 focus:ring-2 focus:ring-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <option value="all">
          All regions{regions.length ? ` (${regions.length})` : ""}
        </option>
        {regions.map((r) => (
          <option key={r} value={r}>
            {regionLabel(r)}
          </option>
        ))}
      </select>
      <ChevronDown
        size={14}
        className="pointer-events-none absolute right-3 text-gray-500"
      />
    </label>
  );
}
