"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DragEndEvent,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragOverEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { useUIStore } from "@/lib/store";
import { api, type Task, type PaginatedResponse } from "@/lib/api";
import { cn, getStatusColor, getPriorityColor, formatRelativeTime } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  ChevronLeft,
  ChevronRight,
  GripVertical,
  MoreVertical,
  Filter,
  X,
  AlertTriangle,
  CheckCircle,
  Clock,
  User,
  Calendar,
  MessageSquare,
  ExternalLink,
  Loader2,
} from "lucide-react";
import { TaskCard } from "./task-card";
import { Column } from "./column";
import { FilterSidebar } from "./filter-sidebar";
import { TaskDetailPanel } from "./task-detail-panel";

export type TaskStatus =
  | "EXTRACTED"
  | "PENDING_REVIEW"
  | "VERIFIED"
  | "ASSIGNED"
  | "SYNCED"
  | "COMPLETED"
  | "DISMISSED";

export const KANBAN_COLUMNS: { id: TaskStatus; title: string; color: string }[] = [
  { id: "EXTRACTED", title: "Extracted", color: "extracted" },
  { id: "PENDING_REVIEW", title: "Pending Review", color: "pending" },
  { id: "VERIFIED", title: "Verified", color: "verified" },
  { id: "ASSIGNED", title: "Assigned", color: "assigned" },
  { id: "SYNCED", title: "Synced", color: "synced" },
  { id: "COMPLETED", title: "Completed", color: "completed" },
  { id: "DISMISSED", title: "Dismissed", color: "dismissed" },
];

const VALID_TRANSITIONS: Record<TaskStatus, TaskStatus[]> = {
  EXTRACTED: ["PENDING_REVIEW", "VERIFIED", "DISMISSED"],
  PENDING_REVIEW: ["VERIFIED", "DISMISSED"],
  VERIFIED: ["ASSIGNED", "PENDING_REVIEW", "DISMISSED"],
  ASSIGNED: ["SYNCED", "COMPLETED", "PENDING_REVIEW", "DISMISSED"],
  SYNCED: ["COMPLETED", "SYNC_FAILED", "CONFLICT", "DISMISSED"],
  SYNC_FAILED: ["SYNCED", "DISMISSED"],
  CONFLICT: ["SYNCED", "DISMISSED"],
  COMPLETED: [],
  DISMISSED: [],
};

export function ExecutionBoard() {
  const { taskFilters, setTaskFilters, viewMode, setViewMode, selectedTask, closeTaskDetail } = useUIStore();
  const queryClient = useQueryClient();

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const { data: tasksResponse, isLoading } = useQuery({
    queryKey: ["tasks", taskFilters],
    queryFn: () => api.getTasks({ ...taskFilters, page_size: 500 }),
  });

  const updateTaskMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Task> }) => api.updateTask(id, data),
    onMutate: async ({ id, data }) => {
      await queryClient.cancelQueries({ queryKey: ["tasks"] });
      const previousTasks = queryClient.getQueryData<PaginatedResponse<Task>>(["tasks", taskFilters]);
      
      queryClient.setQueryData<PaginatedResponse<Task>>(["tasks", taskFilters], (old) => {
        if (!old) return old;
        return {
          ...old,
          items: old.items.map((task) =>
            task.id === id ? { ...task, ...data } : task
          ),
        };
      });
      
      return { previousTasks };
    },
    onError: (err, variables, context) => {
      if (context?.previousTasks) {
        queryClient.setQueryData(["tasks", taskFilters], context.previousTasks);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });

  const handleDragEnd = React.useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;

      // Check if dropped on a column
      const targetColumn = over.id as TaskStatus;
      const activeTask = tasksResponse?.items.find((t) => t.id === active.id);
      
      if (!activeTask) return;

      // Validate transition
      const validTargets = VALID_TRANSITIONS[activeTask.status] || [];
      if (!validTargets.includes(targetColumn)) {
        // Invalid transition - show feedback
        return;
      }

      updateTaskMutation.mutate({
        id: active.id as string,
        data: { status: targetColumn },
      });
    },
    [tasksResponse, updateTaskMutation]
  );

  // Group tasks by status
  const tasksByStatus = React.useMemo(() => {
    return KANBAN_COLUMNS.reduce((acc, column) => {
      acc[column.id] = tasksResponse?.items.filter((t) => t.status === column.id) || [];
      return acc;
    }, {} as Record<TaskStatus, Task[]>);
  }, [tasksResponse]);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="animate-spin h-8 w-8 text-primary" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b p-4">
        <div>
          <h1 className="text-2xl font-bold">Execution Board</h1>
          <p className="text-sm text-muted-foreground">
            {tasksResponse?.total || 0} tasks across {KANBAN_COLUMNS.length} stages
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant={viewMode === "kanban" ? "default" : "outline"}
            size="icon"
            onClick={() => setViewMode("kanban")}
            aria-label="Kanban view"
          >
            <GripVertical className="h-4 w-4" />
          </Button>
          <Button
            variant={viewMode === "list" ? "default" : "outline"}
            size="icon"
            onClick={() => setViewMode("list")}
            aria-label="List view"
          >
            <ChevronLeft className="h-4 w-4" />
            <ChevronRight className="h-4 w-4 ml-1" />
          </Button>
          <FilterSidebar />
        </div>
      </div>

      {/* Kanban Board */}
      <div className="flex-1 overflow-auto p-4">
        <SortableContext
          items={KANBAN_COLUMNS.map((c) => c.id)}
          strategy={verticalListSortingStrategy}
          collisionDetection={closestCenter}
        >
          <div className="flex gap-4 h-full min-h-0">
            {KANBAN_COLUMNS.map((column) => (
              <Column
                key={column.id}
                column={column}
                tasks={tasksByStatus[column.id]}
                onTaskClick={(task) => useUIStore.getState().openTaskDetail(task)}
              />
            ))}
          </div>
        </SortableContext>
      </div>

      {/* Task Detail Panel */}
      {selectedTask && (
        <TaskDetailPanel task={selectedTask} onClose={closeTaskDetail} />
      )}
    </div>
  );
}