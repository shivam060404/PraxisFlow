"use client";

import * as React from "react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

interface ExtractionAccuracyChartProps {
  data: Array<{ week: string; precision: number; recall: number; f1: number }>;
  lines?: string[];
}

export function ExtractionAccuracyChart({ data, lines = ["precision", "recall", "f1"] }: ExtractionAccuracyChartProps) {
  const lineConfig = {
    precision: { label: "Precision", color: "hsl(var(--primary))" },
    recall: { label: "Recall", color: "hsl(var(--status-verified))" },
    f1: { label: "F1 Score", color: "hsl(var(--status-completed))" },
  };

  return (
    <Card>
      <CardContent className="p-4">
        <h3 className="text-sm font-medium mb-4">Extraction Accuracy</h3>
        <ChartContainer
          config={lines.reduce((acc, key) => ({ ...acc, [key]: lineConfig[key as keyof typeof lineConfig] }), {})}
        >
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted/50" />
              <XAxis dataKey="week" className="text-xs" tickLine={false} axisLine={false} />
              <YAxis
                className="text-xs"
                tickLine={false}
                axisLine={false}
                tickFormatter={(value) => `${Math.round(value * 100)}%`}
                domain={[0.5, 1]}
              />
              <Tooltip
                content={<ChartTooltipContent />}
                formatter={(value: number) => [`${Math.round(value * 100)}%`, ""]}
                labelFormatter={(label) => `Week ${label}`}
              />
              <Legend />
              {lines.map((key, index) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={lineConfig[key as keyof typeof lineConfig].color}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 6 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}