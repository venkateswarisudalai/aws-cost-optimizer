import { Badge } from "@tremor/react";
import type { Severity } from "../lib/types";

const styles: Record<Severity, "red" | "amber" | "gray"> = {
  high: "red",
  medium: "amber",
  low: "gray",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <Badge color={styles[severity]} size="xs">
      {severity.toUpperCase()}
    </Badge>
  );
}
