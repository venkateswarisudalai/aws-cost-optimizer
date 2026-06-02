/**
 * Human-friendly names for AWS regions. Falls back to the raw code for any
 * region not in the map, so new regions still render sensibly.
 */
const REGION_NAMES: Record<string, string> = {
  "us-east-1": "N. Virginia",
  "us-east-2": "Ohio",
  "us-west-1": "N. California",
  "us-west-2": "Oregon",
  "af-south-1": "Cape Town",
  "ap-east-1": "Hong Kong",
  "ap-south-1": "Mumbai",
  "ap-south-2": "Hyderabad",
  "ap-southeast-1": "Singapore",
  "ap-southeast-2": "Sydney",
  "ap-southeast-3": "Jakarta",
  "ap-southeast-4": "Melbourne",
  "ap-northeast-1": "Tokyo",
  "ap-northeast-2": "Seoul",
  "ap-northeast-3": "Osaka",
  "ca-central-1": "Central Canada",
  "ca-west-1": "Calgary",
  "eu-central-1": "Frankfurt",
  "eu-central-2": "Zurich",
  "eu-west-1": "Ireland",
  "eu-west-2": "London",
  "eu-west-3": "Paris",
  "eu-north-1": "Stockholm",
  "eu-south-1": "Milan",
  "eu-south-2": "Spain",
  "me-south-1": "Bahrain",
  "me-central-1": "UAE",
  "il-central-1": "Tel Aviv",
  "sa-east-1": "São Paulo",
};

/** "N. California" for "us-west-1", else the raw code. */
export function regionName(code: string): string {
  return REGION_NAMES[code] ?? code;
}

/** "us-west-1 · N. California" — code first so it stays greppable. */
export function regionLabel(code: string): string {
  const name = REGION_NAMES[code];
  return name ? `${code} · ${name}` : code;
}
