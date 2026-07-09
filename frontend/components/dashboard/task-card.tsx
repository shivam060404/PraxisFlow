"use client";

import * as React from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { cn, getStatusColor, getPriorityColor, formatRelativeTime, truncate } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  AlertTriangle,
  CheckCircle,
  Clock,
  User,
  Calendar,
  MessageSquare,
  ExternalLink,
  GripVertical,
  MoreVertical,
  Flag,
} from "lucide-react";
import type { Task } from "@/lib/api";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";

interface TaskCardProps {
  task: Task;
  onClick: () => void;
  isDragging?: boolean;
  dragHandleProps?: React.HTMLAttributes<HTMLButtonElement>;
}

export function TaskCard({
  task,
  onClick,
  isDragging = false,
  dragHandleProps,
}: TaskCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging: sortableIsDragging,
  } = useSortable({ id: task.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: sortableIsDragging ? 0.5 : 1,
  };

  const priorityColors: Record<string, string> = {
    HIGH: "bg-destructive/10 text-destructive border-destructive/20",
    MEDIUM: "bg-amber/10 text-amber-600 border-amber/20",
    LOW: "bg-muted text-muted-foreground",
  };

  const typeIcons: Record<string, React.ReactNode> = {
    ACTION_ITEM: <CheckCircle className="h-3.5 w-3.5" />,
    DECISION: <Flag className="h-3.5 w-3.5" />,
    FOLLOW_UP: <MessageSquare className="h-3.5 w-3.5" />,
    BLOCKER: <AlertTriangle className="h-3.5 w-3.5" />,
  };

  return (
    <div
      ref={(el) => {
        setNodeRef(el);
      }}
      style={style}
      className={cn(
        "group cursor-pointer hover:shadow-md transition-all duration-200",
        sortableIsDragging && "shadow-lg ring-2 ring-primary ring-offset-2 rotate-1",
        isDragging && "opacity-50"
      )}
    >
      <Card className="overflow-hidden">
        <CardContent className="p-3">
          {/* Drag Handle + Header */}
          <div className="flex items-start gap-2 mb-2">
            <button
              {...attributes}
              {...listeners}
              {...dragHandleProps}
              className="flex items-center justify-center p-1 text-muted-foreground/50 hover:text-muted-foreground transition-colors rounded"
              aria-label="Drag to reorder"
            >
              <GripVertical className="h-4 w-4" />
            </button>

            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <h4 className="font-medium text-sm truncate pr-2">{task.title}</h4>
                <Badge variant="status" status={task.status as any} className="text-xs shrink-0">
                  {task.status.replace(/_/g, " ")}
                </Badge>
              </div>
              
              {task.priority && (
                <Badge
                  variant="outline"
                  className={cn("text-xs mt-1", priorityColors[task.priority])}
                >
                  {task.priority}
                </Badge>
              )}
            </div>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity">
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <DropdownMenuItem onClick={onClick}>
                  View Details
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => onClick()}>
                  Edit Task
                </DropdownMenuItem>
                <DropdownMenuItem 
                  className="text-destructive"
                  onClick={() => console.log("Dismiss", task.id)}
                >
                  Dismiss
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          {/* Description */}
          <p className="text-sm text-muted-foreground mb-3 line-clamp-2">
            {task.description}
          </p>

          {/* Meta Information */}
          <div className="space-y-2 text-xs">
            {task.assignee && (
              <div className="flex items-center gap-1.5 text-muted-foreground">
                <User className="h-3.5 w-3.5" />
                <span className="truncate">{task.assignee.full_name || task.assignee.email}</span>
              </div>
            )}
            
            {task.assignee_hint && !task.assignee && (
              <div className="flex items-center gap-1.5 text-amber-600">
                <User className="h-3.5 w-3.5" />
                <span className="truncate">{task.assignee_hint} (unresolved)</span>
              </div>
            )}

            {task.deadline_date && (
              <div className="flex items-center gap-1.5 text-muted-foreground">
                <Calendar className="h-3.5 w-3.5" />
                <span>
                  {new Date(task.deadline_date).toLocaleDateString()}
                  {task.deadline_hint && ` (${task.deadline_hint})`}
                </span>
              </div>
            )}

            {task.deadline_hint && !task.deadline_date && (
              <div className="flex items-center gap-1.5 text-amber-600">
                <Calendar className="h-3.5 w-3.5" />
                <span className="truncate">{task.deadline_hint} (unresolved)</span>
              </div>
            )}

            {task.verification_status === "NEEDS_REVIEW" && task.verification_reasoning && (
              <div className="flex items-start gap-1.5 text-amber-600 p-2 bg-amber-50 rounded text-xs">
                <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
                <span className="truncate">{task.verification_reasoning}</span>
              </div>
            )}

            {task.verification_status === "FAILED" && task.verification_reasoning && (
              <div className="flex items-start gap-1.5 text-destructive p-2 bg-destructive/10 rounded text-xs">
                <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
                <span className="truncate">{task.verification_reasoning}</span>
              </div>
            )}

            {task.external_id && (
              <div className="flex items-center gap-1.5 text-muted-foreground">
                <ExternalLink className="h-3.5 w-3.5" />
                <span className="truncate font-mono text-xs">{task.external_id}</span>
              </div>
            )}
          </div>

          {/* Source Quote */}
          <Separator className="my-2" />
          <div className="flex items-start gap-2 p-2 bg-muted/30 rounded text-xs">
            <MessageSquare className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <p className="font-medium text-muted-foreground mb-1">Source</p>
              <p className="text-muted-foreground/80 italic truncate">
                "{truncate(task.source_quote, 150)}"
              </p>
            </div>
          </div>

          {/* Confidence */}
          <div className="flex items-center justify-between mt-2 pt-2 border-t">
            <div className="flex items-center gap-2">
              {typeIcons[task.task_type] || <CheckCircle className="h-3.5 w-3.5" />}
              <span className="text-xs text-muted-foreground capitalize">
                {task.task_type.toLowerCase().replace(/_/g, " ")}
              </span>
            </div>
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <span className={cn(
                "px-1.5 py-0.5 rounded",
                task.extraction_confidence >= 0.8 ? "bg-green-100 text-green-700" :
                task.extraction_confidence >= 0.6 ? "bg-amber-100 text-amber-700" :
                "bg-red-100 text-red-700"
              )}>
                {Math.round(task.extraction_confidence * 100)}%
              </span>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}