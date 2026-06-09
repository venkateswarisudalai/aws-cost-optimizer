export type Severity = "high" | "medium" | "low";
export type Confidence = "high" | "medium" | "low";
export type Category = "waste" | "rightsizing" | "commitment" | "anomaly";

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
  demo: boolean;
}
