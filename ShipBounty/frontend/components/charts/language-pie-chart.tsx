"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

const COLORS = ["#2563EB", "#10b981", "#8b5cf6", "#f59e0b", "#ef4444", "#06b6d4", "#ec4899"];

interface LanguagePieChartProps {
  breakdown: Record<string, number>;
}

export function LanguagePieChart({ breakdown }: LanguagePieChartProps) {
  const data = Object.entries(breakdown).map(([name, value]) => ({ name, value }));

  if (data.length === 0) {
    return (
      <div className="flex h-56 items-center justify-center rounded-lg border border-dashed border-[#E2E8F0] text-sm text-[#64748B]">
        No language data available
      </div>
    );
  }

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={55}
            outerRadius={90}
            paddingAngle={3}
            dataKey="value"
          >
            {data.map((_, index) => (
              <Cell key={index} fill={COLORS[index % COLORS.length]} stroke="transparent" />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{
              backgroundColor: "#ffffff",
              border: "1px solid #E2E8F0",
              borderRadius: "8px",
              color: "#0F172A",
              boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
            }}
          />
        </PieChart>
      </ResponsiveContainer>
      <div className="mt-3 flex flex-wrap justify-center gap-3">
        {data.map((item, index) => (
          <div key={item.name} className="flex items-center gap-1.5 text-xs text-[#64748B]">
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: COLORS[index % COLORS.length] }}
            />
            {item.name} ({item.value})
          </div>
        ))}
      </div>
    </div>
  );
}
