import type { Finding } from "./types";

/** Savings this finding adds to a total. Alternatives (a smaller option for a
 *  resource that a bigger finding already covers) count as $0 so totals show
 *  what you can actually save, not the sum of mutually exclusive options. */
export function countedSavings(f: Finding): number {
  return f.superseded_by ? 0 : f.monthly_savings_usd;
}
