"use client";

import { Button, Card, Text, Title } from "@tremor/react";
import { Play } from "lucide-react";

export function EmptyState({
  onScan,
  scanning,
}: {
  onScan: () => void;
  scanning: boolean;
}) {
  return (
    <Card className="text-center py-12">
      <Title>No scans yet</Title>
      <Text className="mt-2">
        Click below to scan your AWS account. Your credentials never leave this
        machine.
      </Text>
      <div className="mt-6 flex justify-center">
        <Button
          icon={Play}
          loading={scanning}
          loadingText="Scanning all regions…"
          onClick={onScan}
        >
          Run scan
        </Button>
      </div>
      <Text className="mt-6 text-xs text-gray-500">
        Tip: launch with <code>--demo-data</code> to preview without AWS access.
      </Text>
    </Card>
  );
}
