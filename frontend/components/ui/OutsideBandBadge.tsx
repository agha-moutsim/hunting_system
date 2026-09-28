"use client";

import Badge from "@/components/ui/Badge";

export default function OutsideBandBadge() {
  return (
    <Badge tone="warn" title="Outside active range">
      ⚠️ outside band
    </Badge>
  );
}
