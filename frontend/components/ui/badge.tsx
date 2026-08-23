import * as React from "react";
import { cn } from "@/lib/utils";

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "secondary" | "destructive" | "outline" | "status";
  status?: "extracted" | "pending" | "verified" | "assigned" | "synced" | "completed" | "dismissed";
}

type BadgeVariant = NonNullable<BadgeProps["variant"]>;

const baseVariants: Record<
  Exclude<BadgeVariant, "status">,
  string
> & { status: Record<NonNullable<BadgeProps["status"]>, string> } = {
  default: "border-transparent bg-primary text-primary-foreground hover:bg-primary/80",
  secondary: "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
  destructive: "border-transparent bg-destructive text-destructive-foreground hover:bg-destructive/80",
  outline: "text-foreground",
  status: {
    extracted: "bg-status-extracted/10 text-status-extracted border-status-extracted/20",
    pending: "bg-status-pending/10 text-status-pending border-status-pending/20",
    verified: "bg-status-verified/10 text-status-verified border-status-verified/20",
    assigned: "bg-status-assigned/10 text-status-assigned border-status-assigned/20",
    synced: "bg-status-synced/10 text-status-synced border-status-synced/20",
    completed: "bg-status-completed/10 text-status-completed border-status-completed/20",
    dismissed: "bg-status-dismissed/10 text-muted-foreground border-status-dismissed/20",
  },
};

function Badge({ className, variant = "default", status, ...props }: BadgeProps) {
  const baseStyles = "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2";

  let variantStyles = "";
  if (variant === "status" && status) {
    variantStyles = baseVariants.status[status];
  } else if (variant !== "status") {
    variantStyles = baseVariants[variant] || baseVariants.default;
  }

  return (
    <div className={cn(baseStyles, variantStyles, className)} {...props} />
  );
}

export { Badge };
