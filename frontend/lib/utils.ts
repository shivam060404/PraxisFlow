import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(date: string | Date, format: string = "PPp") {
  const d = new Date(date);
  return d.toLocaleString("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function formatRelativeTime(date: string | Date) {
  const d = new Date(date);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return formatDate(d, "PP");
}

export function getStatusColor(status: string): string {
  const colors: Record<string, string> = {
    EXTRACTED: "bg-status-extracted/10 text-status-extracted border-status-extracted/20",
    PENDING_REVIEW: "bg-status-pending/10 text-status-pending border-status-pending/20",
    VERIFIED: "bg-status-verified/10 text-status-verified border-status-verified/20",
    ASSIGNED: "bg-status-assigned/10 text-status-assigned border-status-assigned/20",
    SYNCED: "bg-status-synced/10 text-status-synced border-status-synced/20",
    COMPLETED: "bg-status-completed/10 text-status-completed border-status-completed/20",
    DISMISSED: "bg-status-dismissed/10 text-status-dismissed border-status-dismissed/20",
  };
  return colors[status] || "bg-muted text-muted-foreground";
}

export function getPriorityColor(priority: string): string {
  const colors: Record<string, string> = {
    HIGH: "bg-destructive/10 text-destructive border-destructive/20",
    MEDIUM: "bg-status-pending/10 text-status-pending border-status-pending/20",
    LOW: "bg-muted text-muted-foreground",
  };
  return colors[priority] || "bg-muted text-muted-foreground";
}

export function getTaskTypeIcon(type: string): string {
  const icons: Record<string, string> = {
    ACTION_ITEM: "checkbox",
    DECISION: "gavel",
    FOLLOW_UP: "arrow-right-circle",
    BLOCKER: "alert-triangle",
  };
  return icons[type] || "circle";
}

export function truncate(text: string, length: number): string {
  if (text.length <= length) return text;
  return text.slice(0, length) + "...";
}

export function debounce<T extends (...args: unknown[]) => unknown>(
  fn: T,
  ms: number
): (...args: Parameters<T>) => void {
  let timeoutId: ReturnType<typeof setTimeout>;
  return (...args: Parameters<T>) => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => fn(...args), ms);
  };
}