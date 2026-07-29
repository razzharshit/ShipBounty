"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { checkHealth } from "@/services/api";

export function StatusBadge() {
  const [connected, setConnected] = useState<boolean | null>(null);

  useEffect(() => {
    checkHealth().then(setConnected);
    const interval = setInterval(() => checkHealth().then(setConnected), 30000);
    return () => clearInterval(interval);
  }, []);

  if (connected === null) {
    return (
      <Badge variant="outline" className="border-[#E2E8F0] bg-[#F1F5F9] text-[#64748B]">
        <span className="mr-1.5 h-1.5 w-1.5 animate-pulse rounded-full bg-[#94A3B8]" />
        Checking...
      </Badge>
    );
  }

  if (!connected) {
    return (
      <Badge variant="outline" className="border-red-200 bg-red-50 text-red-700">
        <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-red-500" />
        Backend Offline
      </Badge>
    );
  }

  return (
    <Badge variant="outline" className="border-green-200 bg-[#DCFCE7] text-[#15803D]">
      <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-[#15803D]" />
      Backend Connected
    </Badge>
  );
}
