"use client";

import * as React from "react";
import { useDroppable } from "@dnd-kit/core";
import { Plus, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { TaskCard } from "./task-card";
import type { Task } from "@/lib/api";

interface ColumnProps {
  column: { id: string; title: string; color: string };
  tasks: Task[];
  onTaskClick: (task: Task) => void;
}

export function Column({ column, tasks, onTaskClick }: ColumnProps) {
  const { setNodeRef, isOver } = useDroppable({ id: column.id });

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "flex flex-col h-full min-w-[300px] max-w-[350px] bg-muted/50 rounded-lg border",
        isOver && "ring-2 ring-primary ring-offset-2"
      )}
    >
      {/* Column Header */}
      <div className="flex items-center justify-between p-3 border-b bg-background/50 sticky top-0 z-10 rounded-t-lg">
        <div className="flex items-center gap-2">
          <Badge variant="status" status={column.id.toLowerCase() as any} className="text-xs font-medium">
            {column.title}
          </Badge>
          <span className="text-sm font-medium text-muted-foreground">
            {tasks.length}
          </span>
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6">
          <ChevronDown className="h-4 w-4" />
        </Button>
      </div>

      {/* Tasks List */}
      <ScrollArea className="flex-1 min-h-0">
        <div className={cn("p-2 space-y-2", isOver && "bg-primary/5")}>
          {tasks.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              onClick={() => onTaskClick(task)}
            />
          ))}

          {/* Drop Zone Indicator */}
          {isOver && (
            <div className="h-8 border-2 border-dashed border-primary/50 rounded-lg bg-primary/5 flex items-center justify-center">
              <span className="text-sm text-primary/70 font-medium">Drop here</span>
            </div>
          )}

          {/* Empty State */}
          {tasks.length === 0 && !isOver && (
            <div className="h-20 border-2 border-dashed border-muted/50 rounded-lg flex items-center justify-center text-muted-foreground/50 text-sm">
              No tasks
            </div>
          )}
        </div>
      </ScrollArea>

      {/* Add Task Button */}
      <div className="p-3 border-t bg-background/50 rounded-b-lg">
        <Button variant="outline" className="w-full justify-start gap-2" size="sm">
          <Plus className="h-4 w-4" />
          Add Task
        </Button>
      </div>
    </div>
  );
}
