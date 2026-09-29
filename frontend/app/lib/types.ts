export type Severity = "high" | "medium" | "low";
export type Confidence = "high" | "medium" | "low";
export type Category = "waste" | "rightsizing" | "commitment" | "anomaly" | "hygiene";
export type RiskLevel = "safe" | "restart" | "destructive" | "commitment" | "info";

/** How to act on a finding — the same four answers for every check. */
export interface Guidance {
  recommendation: string;
  risk_level: RiskLevel;
  risks: string[];
  before_you_act: string[];
  undo: string;
  reversible: boolean;
}

export interface Finding {
  id: string;
  check_id: string;
  title: string;
  description: string;
  service: string;
  region: string;
  resource_arn: string;
  resource_id: string;
  monthly_savings_usd: number;
  // Older scans (pre-FinOps) won't carry a category — treat missing as "waste".
  category?: Category;
  severity: Severity;
  confidence: Confidence;
  cli_fix_command: string;
  fix_destructive: boolean;
  evidence: Record<string, unknown>;
  // Set when a bigger-saving finding covers the same resource / commitment
  // pool — an alternative, so it's left out of savings totals.
  superseded_by?: string | null;
  guidance?: Guidance | null;
  detected_at: string;
}

export interface ScanResult {
  scan_id: string;
  account_id: string | null;
  started_at: string;
  finished_at: string | null;
  regions_scanned: string[];
  findings: Finding[];
  errors: { collector: string; region: string; error: string }[];
  is_demo: boolean;
  lookback_days?: number;
  spend?: SpendSummary | null;
}

/** Cost Explorer spend baseline (null when Cost Explorer isn't available). */
export interface SpendSummary {
  period_start: string;
  period_end: string;
  total_30d_usd: number;
  by_service: { service: string; cost_usd: number }[];
  month_to_date_usd: number | null;
  forecast_month_usd: number | null;
  currency: string;
}

export interface AwsCredentials {
  access_key_id: string;
  secret_access_key: string;
  session_token?: string | null;
}

export interface RegionInfo {
  name: string;
  opt_in_status: string;
  enabled: boolean;
}

export interface ValidateResult {
  account_id: string;
  arn: string;
  regions: RegionInfo[];
  warnings?: string[];
  demo: boolean;
}
