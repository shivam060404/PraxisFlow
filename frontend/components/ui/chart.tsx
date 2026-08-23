"use client";

import * as React from "react";
import { Tooltip } from "recharts";
import { cn } from "@/lib/utils";

const ChartContainer = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & {
    config?: Record<string, { label: string; color: string }>;
  }
>(({ className, config, children, ...props }, ref) => (
  <div ref={ref} className={cn("w-full h-full", className)} {...props}>
    <div className="relative w-full h-full">{children}</div>
    {config && (
      <div className="flex flex-wrap items-center justify-center gap-4 mt-4 text-xs text-muted-foreground">
        {Object.entries(config).map(([key, { label, color }]) => (
          <div key={key} className="flex items-center gap-1.5">
            <div className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
            <span>{label}</span>
          </div>
        ))}
      </div>
    )}
  </div>
));
ChartContainer.displayName = "ChartContainer";

const ChartTooltip = React.forwardRef<
  React.ElementRef<typeof Tooltip>,
  Omit<React.ComponentPropsWithoutRef<typeof Tooltip>, "content">
>(({ ...props }, ref) => (
  <Tooltip ref={ref} content={<ChartTooltipContent />} {...props} />
));
ChartTooltip.displayName = "ChartTooltip";

function ChartTooltipContent({ active, payload, label }: { active?: boolean; payload?: Array<{ value: number; name: string; color: string }>; label?: string }) {
  if (!active || !payload) return null;
  return (
    <div className="rounded-lg border bg-background p-3 shadow-lg">
      <p className="font-medium text-muted-foreground">{label}</p>
      {payload.map((item, index) => (
        <p key={index} className="text-sm" style={{ color: item.color }}>
          {item.name}: {item.value}
        </p>
      ))}
    </div>
  );
}

const ChartLegend = React.forwardRef<
  React.ElementRef<typeof ChartLegendContent>,
  React.ComponentPropsWithoutRef<typeof ChartLegendContent>
>(({ className, ...props }, ref) => (
  <ChartLegendContent ref={ref} className={cn("", className)} {...props} />
));
ChartLegend.displayName = "ChartLegend";

const ChartLegendContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn("flex flex-wrap items-center justify-center gap-4", className)} {...props} />
));
ChartLegendContent.displayName = "ChartLegendContent";

export { ChartContainer, ChartTooltip, ChartTooltipContent, ChartLegend, ChartLegendContent };