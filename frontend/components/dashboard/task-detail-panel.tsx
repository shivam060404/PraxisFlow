"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  X,
  User,
  Calendar,
  Clock,
  AlertTriangle,
  CheckCircle,
  MessageSquare,
  ExternalLink,
  Gavel,
  Flag,
  ArrowRightCircle,
  Loader2,
  ChevronLeft,
  ChevronRight,
  Edit,
  Trash2,
  Copy,
} from "lucide-react";
import type { Task } from "@/lib/api";
import { api } from "@/lib/api";
import { formatRelativeTime, getStatusColor, getPriorityColor, truncate } from "@/lib/utils";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, DropdownMenuSeparator, DropdownMenuLabel } from "@/components/ui/dropdown-menu";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useUIStore } from "@/lib/store";

const typeIcons = {
  ACTION_ITEM: CheckCircle,
  DECISION: Gavel,
  FOLLOW_UP: ArrowRightCircle,
  BLOCKER: AlertTriangle,
};

const typeLabels = {
  ACTION_ITEM: "Action Item",
  DECISION: "Decision",
  FOLLOW_UP: "Follow Up",
  BLOCKER: "Blocker",
};

interface TaskDetailPanelProps {
  task: Task;
  onClose: () => void;
}

export function TaskDetailPanel({ task, onClose }: TaskDetailPanelProps) {
  const queryClient = useQueryClient();
  const { openTaskDetail } = useUIStore();

  const [editing, setEditing] = React.useState(false);
  const [editTitle, setEditTitle] = React.useState(task.title);
  const [editDescription, setEditDescription] = React.useState(task.description);
  const [editPriority, setEditPriority] = React.useState(task.priority || "");
  const [editAssigneeHint, setEditAssigneeHint] = React.useState(task.assignee_hint || "");
  const [editDeadlineHint, setEditDeadlineHint] = React.useState(task.deadline_hint || "");

  const updateTaskMutation = useMutation({
    mutationFn: (data: Partial<Task>) => api.updateTask(task.id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      setEditing(false);
    },
  });

  const verifyTaskMutation = useMutation({
    mutationFn: ({ status, reasoning }: { status: string; reasoning?: string }) =>
      api.verifyTask(task.id, status, reasoning),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });

  const assignTaskMutation = useMutation({
    mutationFn: (assigneeId: string) => api.assignTask(task.id, assigneeId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });

  const dismissTaskMutation = useMutation({
    mutationFn: (reason: string) => api.dismissTask(task.id, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      onClose();
    },
  });

  const handleSave = () => {
    updateTaskMutation.mutate({
      title: editTitle,
      description: editDescription,
      priority: editPriority as any,
      assignee_hint: editAssigneeHint,
      deadline_hint: editDeadlineHint,
    });
  };

  const handleVerify = (status: string, reasoning?: string) => {
    verifyTaskMutation.mutate({ status, reasoning });
  };

  const handleAssign = (assigneeId: string) => {
    assignTaskMutation.mutate(assigneeId);
  };

  const handleDismiss = (reason: string) => {
    dismissTaskMutation.mutate(reason);
  };

  const IconComponent = typeIcons[task.task_type as keyof typeof typeIcons] || CheckCircle;

  return (
    <div className="fixed right-0 top-0 z-50 h-full w-full max-w-2xl bg-background shadow-xl animate-slide-in-right" style={{ boxShadow: "-4px 0 20px rgba(0,0,0,0.1)" }}>
      <div className="flex h-full flex-col">
        {/* Header */}
        <div className="flex items-center justify-between border-b p-4 sticky top-0 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" onClick={onClose} className="h-8 w-8">
              <X className="h-4 w-4" />
            </Button>
            <div>
              <p className="font-medium text-sm text-muted-foreground">Task Details</p>
              <p className="text-xs text-muted-foreground">{task.id.slice(0, 8)}...</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="status" status={task.status as any} className="text-xs">
              {task.status.replace(/_/g, " ")}
            </Badge>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-8 w-8">
                  <ChevronLeft className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <DropdownMenuLabel>Actions</DropdownMenuLabel>
                <DropdownMenuItem onClick={() => setEditing(true)}>
                  <Edit className="h-4 w-4 mr-2" />
                  Edit
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => navigator.clipboard.writeText(task.id)}>
                  <Copy className="h-4 w-4 mr-2" />
                  Copy ID
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem className="text-destructive" onClick={() => handleDismiss("")}>
                  <Trash2 className="h-4 w-4 mr-2" />
                  Dismiss
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {/* Content */}
        <ScrollArea className="flex-1 overflow-y-auto">
          <div className="p-4 space-y-6">
            {/* Main Task Info */}
            <div className="space-y-4">
              {/* Title & Type */}
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                  <IconComponent className="h-5 w-5 text-primary" />
                </div>
                <div className="flex-1 min-w-0">
                  {editing ? (
                    <Input
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      className="text-lg font-semibold"
                      placeholder="Task title"
                    />
                  ) : (
                    <h2 className="text-lg font-semibold truncate">{task.title}</h2>
                  )}
                  <div className="flex items-center gap-2 mt-1">
                    <Badge variant="outline" className="text-xs">
                      {typeLabels[task.task_type as keyof typeof typeLabels] || task.task_type}
                    </Badge>
                    {task.priority && (
                      <Badge variant="outline" className={getPriorityColor(task.priority)}>
                        {task.priority}
                      </Badge>
                    )}
                  </div>
                </div>
              </div>

              {/* Description */}
              <div>
                <Label className="text-sm font-medium text-muted-foreground">Description</Label>
                {editing ? (
                  <Textarea
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    className="mt-1"
                    rows={4}
                  />
                ) : (
                  <p className="mt-1 text-sm whitespace-pre-wrap">{task.description}</p>
                )}
              </div>

              {/* Priority & Assignee Hint (Editing) */}
              {editing && (
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label className="text-sm font-medium text-muted-foreground">Priority</Label>
                    <Select value={editPriority} onValueChange={setEditPriority}>
                      <SelectTrigger className="mt-1">
                        <SelectValue placeholder="Select priority" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="HIGH">High</SelectItem>
                        <SelectItem value="MEDIUM">Medium</SelectItem>
                        <SelectItem value="LOW">Low</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="text-sm font-medium text-muted-foreground">Assignee Hint</Label>
                    <Input
                      value={editAssigneeHint}
                      onChange={(e) => setEditAssigneeHint(e.target.value)}
                      placeholder="e.g., John from marketing"
                      className="mt-1"
                    />
                  </div>
                </div>
              )}
            </div>

            <Separator />

            {/* Meta Information */}
            <div className="space-y-3">
              {task.assignee && (
                <div className="flex items-center gap-3 p-3 bg-muted/30 rounded-lg">
                  <Avatar className="h-10 w-10">
                    <AvatarImage src={task.assignee.avatar_url || ""} alt={task.assignee.full_name} />
                    <AvatarFallback>
                      {task.assignee.full_name?.charAt(0).toUpperCase()}
                    </AvatarFallback>
                  </Avatar>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-sm">{task.assignee.full_name}</p>
                    <p className="text-xs text-muted-foreground truncate">{task.assignee.email}</p>
                  </div>
                  <User className="h-5 w-5 text-muted-foreground" />
                </div>
              )}

              {task.assignee_hint && !task.assignee && (
                <div className="flex items-center gap-3 p-3 bg-amber-50 rounded-lg border border-amber/20">
                  <AlertTriangle className="h-5 w-5 text-amber-600" />
                  <div className="flex-1">
                    <p className="font-medium text-sm text-amber-800">Unresolved Assignee</p>
                    <p className="text-xs text-amber-700">{task.assignee_hint}</p>
                  </div>
                  <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                    Resolve
                  </Button>
                </div>
              )}

              {task.deadline_date && (
                <div className="flex items-center gap-3 p-3 bg-muted/30 rounded-lg">
                  <Calendar className="h-5 w-5 text-muted-foreground" />
                  <div>
                    <p className="font-medium text-sm">Deadline</p>
                    <p className="text-sm">{new Date(task.deadline_date).toLocaleDateString()}</p>
                    {task.deadline_hint && (
                      <p className="text-xs text-muted-foreground">({task.deadline_hint})</p>
                    )}
                  </div>
                </div>
              )}

              {task.deadline_hint && !task.deadline_date && (
                <div className="flex items-center gap-3 p-3 bg-amber-50 rounded-lg border border-amber/20">
                  <Calendar className="h-5 w-5 text-amber-600" />
                  <div>
                    <p className="font-medium text-sm text-amber-800">Unresolved Deadline</p>
                    <p className="text-xs text-amber-700">{task.deadline_hint}</p>
                  </div>
                </div>
              )}

              <div className="flex items-center gap-3 p-3 bg-muted/30 rounded-lg">
                <Clock className="h-5 w-5 text-muted-foreground" />
                <div>
                  <p className="font-medium text-sm">Created</p>
                  <p className="text-sm text-muted-foreground">{formatRelativeTime(task.created_at)}</p>
                </div>
              </div>

              {task.external_id && (
                <div className="flex items-center gap-3 p-3 bg-muted/30 rounded-lg">
                  <ExternalLink className="h-5 w-5 text-muted-foreground" />
                  <div className="flex-1">
                    <p className="font-medium text-sm">External Reference</p>
                    <p className="text-sm font-mono text-xs">{task.external_id}</p>
                    {task.external_url && (
                      <a href={task.external_url} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline mt-1 inline-block">
                        Open in external tool
                      </a>
                    )}
                  </div>
                </div>
              )}

              <div className="flex items-center gap-3 p-3 bg-muted/30 rounded-lg">
                <MessageSquare className="h-5 w-5 text-muted-foreground" />
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-sm">Source Quote</p>
                  <p className="text-xs text-muted-foreground italic truncate">
                    "{truncate(task.source_quote, 200)}"
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-3 p-3 bg-muted/30 rounded-lg">
                <div className="flex items-center gap-2">
                  {task.verification_status === "VERIFIED" && (
                    <CheckCircle className="h-5 w-5 text-green-600" />
                  )}
                  {task.verification_status === "NEEDS_REVIEW" && (
                    <AlertTriangle className="h-5 w-5 text-amber-600" />
                  )}
                  {task.verification_status === "FAILED" && (
                    <AlertTriangle className="h-5 w-5 text-red-600" />
                  )}
                  {task.verification_status === "PENDING" && (
                    <Clock className="h-5 w-5 text-muted-foreground" />
                  )}
                </div>
                <div>
                  <p className="font-medium text-sm">Verification</p>
                  <Badge
                    variant="status"
                    status={task.verification_status.toLowerCase() as any}
                    className="text-xs"
                  >
                    {task.verification_status.replace(/_/g, " ")}
                  </Badge>
                  {task.verification_reasoning && (
                    <p className="text-xs text-muted-foreground mt-1">{task.verification_reasoning}</p>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-3 p-3 bg-muted/30 rounded-lg">
                <div className="flex items-center gap-2">
                  <span className={cn(
                    "px-2 py-1 rounded text-xs font-mono",
                    task.extraction_confidence >= 0.8 ? "bg-green-100 text-green-700" :
                    task.extraction_confidence >= 0.6 ? "bg-amber-100 text-amber-700" :
                    "bg-red-100 text-red-700"
                  )}>
                    {Math.round(task.extraction_confidence * 100)}%
                  </span>
                </div>
                <div>
                  <p className="font-medium text-sm text-muted-foreground">Extraction Confidence</p>
                </div>
              </div>
            </div>

            <Separator />

            {/* Actions */}
            <div className="space-y-3">
              <Label className="text-sm font-medium">Actions</Label>
              <div className="flex flex-wrap gap-2">
                {task.status === "PENDING_REVIEW" && (
                  <>
                    <Button
                      size="sm"
                      onClick={() => handleVerify("VERIFIED", "Approved manually")}
                    >
                      <CheckCircle className="h-4 w-4 mr-2" />
                      Approve
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => handleVerify("NEEDS_REVIEW", "Needs more info")}>
                      <AlertTriangle className="h-4 w-4 mr-2" />
                      Request Review
                    </Button>
                  </>
                )}

                {task.status === "VERIFIED" && !task.assignee_id && (
                  <Button size="sm" onClick={() => setEditing(true)}>
                    <User className="h-4 w-4 mr-2" />
                    Assign
                  </Button>
                )}

                {task.status === "ASSIGNED" && (
                  <Button size="sm" variant="outline">
                    <ExternalLink className="h-4 w-4 mr-2" />
                    Sync to Jira
                  </Button>
                )}

                {task.status === "SYNCED" && (
                  <Button size="sm" onClick={() => handleVerify("COMPLETED", "Marked complete")}>
                    <CheckCircle className="h-4 w-4 mr-2" />
                    Mark Complete
                  </Button>
                )}

                <Button variant="ghost" size="sm" className="text-destructive" onClick={() => handleDismiss("Dismissed by user")}>
                  <Trash2 className="h-4 w-4 mr-2" />
                  Dismiss
                </Button>
              </div>
            </div>

            {/* Edit Actions */}
            {editing && (
              <div className="flex gap-2 pt-4 border-t">
                <Button onClick={handleSave}>
                  <CheckCircle className="h-4 w-4 mr-2" />
                  Save Changes
                </Button>
                <Button variant="outline" onClick={() => setEditing(false)}>
                  <X className="h-4 w-4 mr-2" />
                  Cancel
                </Button>
              </div>
            )}
          </div>
        </ScrollArea>

        {/* Tabs for Audit Log & Transcript Context */}
        <div className="border-t">
          <Tabs defaultValue="audit" className="w-full">
            <TabsList className="grid w-full grid-cols-2 p-2">
              <TabsTrigger value="audit">Audit Log</TabsTrigger>
              <TabsTrigger value="transcript">Transcript Context</TabsTrigger>
            </TabsList>
            <TabsContent value="audit" className="p-4">
              <AuditLogTab taskId={task.id} />
            </TabsContent>
            <TabsContent value="transcript" className="p-4">
              <TranscriptContextTab task={task} />
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  );
}

function AuditLogTab({ taskId }: { taskId: string }) {
  const { data } = useQuery({
    queryKey: ["task-audit", taskId],
    queryFn: () => api.getTaskAuditLog(taskId),
  });

  if (!data?.items?.length) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        <p className="text-sm">No audit history yet</p>
      </div>
    );
  }

  return (
    <div className="space-y-3 max-h-64 overflow-y-auto">
      {data.items.map((log) => (
        <div key={log.id} className="flex items-start gap-3 p-3 bg-muted/30 rounded-lg">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10">
            {log.new_status === "COMPLETED" && <CheckCircle className="h-4 w-4 text-primary" />}
            {log.new_status === "DISMISSED" && <AlertTriangle className="h-4 w-4 text-destructive" />}
            {log.new_status === "VERIFIED" && <CheckCircle className="h-4 w-4 text-green-600" />}
            {!log.new_status.match(/COMPLETED|DISMISSED|VERIFIED/) && (
              <Clock className="h-4 w-4 text-muted-foreground" />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <Badge variant="status" status={log.new_status as any} className="text-xs">
                {log.new_status.replace(/_/g, " ")}
              </Badge>
              <span className="text-xs text-muted-foreground">
                by {log.changed_by}
              </span>
            </div>
            {log.reason && (
              <p className="text-xs text-muted-foreground mt-1">{log.reason}</p>
            )}
            <p className="text-xs text-muted-foreground">
              {formatRelativeTime(log.created_at)}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

function TranscriptContextTab({ task }: { task: Task }) {
  const { data } = useQuery({
    queryKey: ["transcript-span", task.meeting_id, task.transcript_word_start, task.transcript_word_end],
    queryFn: () => api.getTranscriptSpan(task.meeting_id, task.transcript_word_start, task.transcript_word_end),
    enabled: !!task.meeting_id,
  });

  if (!data) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        <Loader2 className="animate-spin h-6 w-6 mx-auto mb-2" />
        <p className="text-sm">Loading transcript context...</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="p-3 bg-muted/30 rounded-lg">
        <p className="text-sm font-medium mb-2">Transcript Segment</p>
        <p className="text-sm text-muted-foreground whitespace-pre-wrap">{data.text}</p>
        <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
          <span>Speakers: {data.speakers?.join(", ")}</span>
          <span>{Math.round((data.end_time_ms - data.start_time_ms) / 1000)}s</span>
        </div>
      </div>

      <div className="p-3 bg-muted/30 rounded-lg">
        <p className="text-sm font-medium mb-2">Task Source Quote</p>
        <p className="text-sm text-muted-foreground italic">"{task.source_quote}"</p>
        <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
          <span>Words: {task.transcript_word_start}–{task.transcript_word_end}</span>
          <span>Confidence: {Math.round(task.extraction_confidence * 100)}%</span>
        </div>
      </div>
    </div>
  );
}