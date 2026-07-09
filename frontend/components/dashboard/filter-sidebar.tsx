"use client";

import * as React from "react";
import { useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn, getStatusColor } from "@/lib/utils";
import { Filter, X, ChevronDown, SlidersHorizontal } from "lucide-react";
import { useUIStore } from "@/lib/store";
import { api, type TaskStatus, type Priority } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";

const STATUSES: { value: TaskStatus; label: string }[] = [
  { value: "EXTRACTED", label: "Extracted" },
  { value: "PENDING_REVIEW", label: "Pending Review" },
  { value: "VERIFIED", label: "Verified" },
  { value: "ASSIGNED", label: "Assigned" },
  { value: "SYNCED", label: "Synced" },
  { value: "COMPLETED", label: "Completed" },
  { value: "DISMISSED", label: "Dismissed" },
];

const PRIORITIES: { value: Priority; label: string }[] = [
  { value: "HIGH", label: "High" },
  { value: "MEDIUM", label: "Medium" },
  { value: "LOW", label: "Low" },
];

export function FilterSidebar() {
  const { taskFilters, setTaskFilters, clearTaskFilters } = useUIStore();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState(taskFilters.search || "");

  const { data: users } = useQuery({
    queryKey: ["users"],
    queryFn: () => api.getUsers(),
  });

  const { data: meetings } = useQuery({
    queryKey: ["meetings"],
    queryFn: () => api.getMeetings({ page_size: 100 }),
  });

  const hasFilters = React.useMemo(() => {
    return Object.values(taskFilters).some((v) => 
      Array.isArray(v) ? v.length > 0 : !!v
    );
  }, [taskFilters]);

  const handleSearchChange = (value: string) => {
    setSearch(value);
    setTaskFilters({ search: value || undefined });
  };

  const handleMultiSelectChange = (key: keyof typeof taskFilters, value: string) => {
    const current = (taskFilters[key] as string[]) || [];
    const next = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    setTaskFilters({ [key]: next });
  };

  const handleSingleSelectChange = (key: keyof typeof taskFilters, value: string) => {
    setTaskFilters({ [key]: value || undefined });
  };

  const handleClearAll = () => {
    clearTaskFilters();
    setSearch("");
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant={hasFilters ? "default" : "outline"}
          className="gap-2"
          size="sm"
        >
          <Filter className="h-4 w-4" />
          <span className="hidden sm:inline">Filters</span>
          {hasFilters && (
            <span className="bg-primary text-primary-foreground text-xs px-1.5 py-0.5 rounded-full">
              {Object.values(taskFilters).reduce((acc, v) => 
                acc + (Array.isArray(v) ? v.length : (v ? 1 : 0)), 0)}
            </span>
          )}
        </Button>
      </DialogTrigger>
      
      <DialogContent className="max-w-md max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Filters</DialogTitle>
        </DialogHeader>
        
        <div className="space-y-6 p-4">
          {/* Search */}
          <div>
            <Label className="text-sm font-medium">Search</Label>
            <Input
              placeholder="Search tasks..."
              value={search}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="mt-1"
            />
          </div>
          
          <Separator />
          
          {/* Status */}
          <div>
            <Label className="text-sm font-medium">Status</Label>
            <div className="grid grid-cols-2 gap-2 mt-2">
              {STATUSES.map((status) => (
                <label
                  key={status.value}
                  className={cn(
                    "flex items-center gap-2 p-2 rounded-lg border cursor-pointer transition-colors",
                    taskFilters.status?.includes(status.value)
                      ? "bg-primary/10 border-primary text-primary"
                      : "hover:bg-accent"
                  )}
                >
                  <Checkbox
                    value={status.value}
                    checked={taskFilters.status?.includes(status.value) || false}
                    onCheckedChange={() => handleMultiSelectChange("status", status.value)}
                  />
                  <Badge
                    variant="status"
                    status={status.value as any}
                    className="text-xs flex-1 justify-center"
                  >
                    {status.label}
                  </Badge>
                </label>
              ))}
            </div>
          </div>
          
          <Separator />
          
          {/* Priority */}
          <div>
            <Label className="text-sm font-medium">Priority</Label>
            <div className="flex gap-2 mt-2">
              {PRIORITIES.map((priority) => (
                <label
                  key={priority.value}
                  className={cn(
                    "flex items-center gap-2 p-2 rounded-lg border cursor-pointer transition-colors flex-1",
                    taskFilters.priority?.includes(priority.value)
                      ? "bg-primary/10 border-primary text-primary"
                      : "hover:bg-accent"
                  )}
                >
                  <Checkbox
                    value={priority.value}
                    checked={taskFilters.priority?.includes(priority.value) || false}
                    onCheckedChange={() => handleMultiSelectChange("priority", priority.value)}
                  />
                  <span className="text-sm">{priority.label}</span>
                </label>
              ))}
            </div>
          </div>
          
          <Separator />
          
          {/* Assignee */}
          <div>
            <Label className="text-sm font-medium">Assignee</Label>
            <Select
              value={taskFilters.assignee_id?.[0] || ""}
              onValueChange={(value) => handleSingleSelectChange("assignee_id", value)}
            >
              <SelectTrigger className="mt-1">
                <SelectValue placeholder="All assignees" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">All assignees</SelectItem>
                {users?.items.map((user) => (
                  <SelectItem key={user.id} value={user.id}>
                    {user.full_name} ({user.email})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          
          <Separator />
          
          {/* Meeting */}
          <div>
            <Label className="text-sm font-medium">Meeting</Label>
            <Select
              value={taskFilters.meeting_id?.[0] || ""}
              onValueChange={(value) => handleSingleSelectChange("meeting_id", value)}
            >
              <SelectTrigger className="mt-1">
                <SelectValue placeholder="All meetings" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">All meetings</SelectItem>
                {meetings?.items.map((meeting) => (
                  <SelectItem key={meeting.id} value={meeting.id}>
                    {meeting.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          
          <Separator />
          
          {/* Date Range */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label className="text-sm font-medium">From Date</Label>
              <Input
                type="date"
                value={taskFilters.date_from || ""}
                onChange={(e) => setTaskFilters({ date_from: e.target.value || undefined })}
                className="mt-1"
              />
            </div>
            <div>
              <Label className="text-sm font-medium">To Date</Label>
              <Input
                type="date"
                value={taskFilters.date_to || ""}
                onChange={(e) => setTaskFilters({ date_to: e.target.value || undefined })}
                className="mt-1"
              />
            </div>
          </div>
          
          {hasFilters && (
            <Button variant="outline" className="w-full" onClick={handleClearAll}>
              <X className="h-4 w-4 mr-2" />
              Clear All Filters
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}