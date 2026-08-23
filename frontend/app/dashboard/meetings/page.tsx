"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cn, formatRelativeTime } from "@/lib/utils";
import { api, type Meeting , type PaginatedResponse } from "@/lib/api";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Loader2, Search, Calendar, Upload, Mic, MoreVertical, Play, Trash2, Download, Eye, X } from "lucide-react";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, DropdownMenuSeparator, DropdownMenuLabel } from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { format } from "date-fns";

const statusColors: Record<string, string> = {
  UPLOADED: "bg-blue-100 text-blue-700",
  PROCESSING: "bg-amber-100 text-amber-700",
  TRANSCRIBED: "bg-purple-100 text-purple-700",
  EXTRACTED: "bg-indigo-100 text-indigo-700",
  COMPLETED: "bg-green-100 text-green-700",
  ERROR: "bg-red-100 text-red-700",
};

interface UploadForm {
  file: File | null;
  title: string;
  description: string;
  scheduled_at: string;
  duration_minutes: string;
}

export default function MeetingsPage() {
  const [search, setSearch] = React.useState("");
  const [statusFilter, setStatusFilter] = React.useState<string>("all");
  const [showUploadModal, setShowUploadModal] = React.useState(false);
  const [uploadForm, setUploadForm] = React.useState<UploadForm>({
    file: null,
    title: "",
    description: "",
    scheduled_at: format(new Date(), "yyyy-MM-dd'T'HH:mm"),
    duration_minutes: "",
  });

  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery<PaginatedResponse<Meeting>>({
    queryKey: ["meetings", { search, status: statusFilter }],
    queryFn: () => api.getMeetings({ 
      page_size: 50,
      ...(search && { search }),
      ...(statusFilter !== "all" && { status: statusFilter as any })
    }),
  });

  const uploadMutation = useMutation({
    mutationFn: (formData: FormData) => api.createMeeting(formData),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["meetings"] });
      setShowUploadModal(false);
      setUploadForm({
        file: null,
        title: "",
        description: "",
        scheduled_at: format(new Date(), "yyyy-MM-dd'T'HH:mm"),
        duration_minutes: "",
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteMeeting(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["meetings"] });
    },
  });

  const reprocessMutation = useMutation({
    mutationFn: (id: string) => api.reprocessMeeting(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["meetings"] });
    },
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] || null;
    setUploadForm(prev => ({ ...prev, file }));
    if (file && !uploadForm.title) {
      setUploadForm(prev => ({ ...prev, title: file.name.replace(/\.[^/.]+$/, "") }));
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadForm.file) return;

    const formData = new FormData();
    formData.append("file", uploadForm.file);
    formData.append("title", uploadForm.title);
    formData.append("description", uploadForm.description);
    formData.append("scheduled_at", uploadForm.scheduled_at);
    if (uploadForm.duration_minutes) {
      formData.append("duration_minutes", uploadForm.duration_minutes);
    }

    uploadMutation.mutate(formData);
  };

  return (
    <DashboardLayout>
      <div className="h-[calc(100vh-4rem)] flex flex-col">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 p-4 border-b">
          <div>
            <h1 className="text-2xl font-bold">Meetings</h1>
            <p className="text-sm text-muted-foreground">
              {data?.total || 0} meetings total
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="relative hidden sm:block">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search meetings..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-10 w-64"
              />
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-40 hidden sm:block">
                <SelectValue placeholder="All statuses" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Statuses</SelectItem>
                <SelectItem value="UPLOADED">Uploaded</SelectItem>
                <SelectItem value="PROCESSING">Processing</SelectItem>
                <SelectItem value="TRANSCRIBED">Transcribed</SelectItem>
                <SelectItem value="EXTRACTED">Extracted</SelectItem>
                <SelectItem value="COMPLETED">Completed</SelectItem>
                <SelectItem value="ERROR">Error</SelectItem>
              </SelectContent>
            </Select>
            <Dialog open={showUploadModal} onOpenChange={setShowUploadModal}>
              <DialogTrigger asChild>
                <Button>
                  <Upload className="h-4 w-4 mr-2" />
                  Upload Meeting
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-2xl">
                <DialogHeader>
                  <DialogTitle>Upload Meeting Recording</DialogTitle>
                </DialogHeader>
                <form onSubmit={handleSubmit}>
                  <div className="grid gap-4 py-4">
                    <div className="grid grid-cols-4 items-center gap-4">
                      <Label htmlFor="file" className="text-right">Audio/Video File</Label>
                      <input
                        id="file"
                        type="file"
                        accept="audio/*,video/*"
                        onChange={handleFileChange}
                        className="col-span-3"
                        required={!uploadForm.file}
                        disabled={!!uploadForm.file}
                      />
                      {uploadForm.file && (
                        <div className="col-span-3 text-sm text-muted-foreground">
                          Selected: {uploadForm.file.name} ({(uploadForm.file.size / 1024 / 1024).toFixed(1)} MB)
                          <Button type="button" variant="ghost" size="sm" className="ml-2 h-6" onClick={() => setUploadForm(prev => ({ ...prev, file: null }))}>
                            <X className="h-3 w-3" /> Remove
                          </Button>
                        </div>
                      )}
                    </div>
                    <div className="grid grid-cols-4 items-center gap-4">
                      <Label htmlFor="title" className="text-right">Title</Label>
                      <Input
                        id="title"
                        value={uploadForm.title}
                        onChange={(e) => setUploadForm(prev => ({ ...prev, title: e.target.value }))}
                        className="col-span-3"
                        placeholder="Meeting title"
                        required
                      />
                    </div>
                    <div className="grid grid-cols-4 items-center gap-4">
                      <Label htmlFor="description" className="text-right">Description</Label>
                      <Textarea
                        id="description"
                        value={uploadForm.description}
                        onChange={(e) => setUploadForm(prev => ({ ...prev, description: e.target.value }))}
                        className="col-span-3"
                        placeholder="Optional description"
                        rows={2}
                      />
                    </div>
                    <div className="grid grid-cols-4 items-center gap-4">
                      <Label htmlFor="scheduled_at" className="text-right">Date & Time</Label>
                      <Input
                        id="scheduled_at"
                        type="datetime-local"
                        value={uploadForm.scheduled_at}
                        onChange={(e) => setUploadForm(prev => ({ ...prev, scheduled_at: e.target.value }))}
                        className="col-span-3"
                        required
                      />
                    </div>
                    <div className="grid grid-cols-4 items-center gap-4">
                      <Label htmlFor="duration_minutes" className="text-right">Duration (min)</Label>
                      <Input
                        id="duration_minutes"
                        type="number"
                        value={uploadForm.duration_minutes}
                        onChange={(e) => setUploadForm(prev => ({ ...prev, duration_minutes: e.target.value }))}
                        className="col-span-3"
                        placeholder="Optional"
                      />
                    </div>
                  </div>
                  <DialogFooter>
                    <Button type="button" variant="outline" onClick={() => setShowUploadModal(false)}>
                      Cancel
                    </Button>
                    <Button type="submit" disabled={uploadMutation.isPending || !uploadForm.file}>
                      {uploadMutation.isPending ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Uploading...
                        </>
                      ) : (
                        "Upload & Process"
                      )}
                    </Button>
                  </DialogFooter>
                </form>
              </DialogContent>
            </Dialog>
          </div>
        </div>

        {/* Meetings List */}
        <div className="flex-1 overflow-auto p-4">
          {isLoading ? (
            <div className="flex items-center justify-center h-full">
              <Loader2 className="animate-spin h-8 w-8 text-primary" />
            </div>
          ) : (
            <div className="space-y-3">
              {data?.items.map((meeting) => (
                <Card key={meeting.id} className="hover:shadow-md transition-shadow cursor-pointer" onClick={() => window.location.href = `/dashboard/meetings/${meeting.id}`}>
                  <CardContent className="p-4">
                    <div className="flex items-start gap-4">
                      <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10">
                        <Mic className="h-6 w-6 text-primary" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-4">
                          <div className="flex-1 min-w-0">
                            <h3 className="font-semibold truncate">{meeting.title}</h3>
                            <p className="text-sm text-muted-foreground truncate mt-1">
                              {meeting.description || "No description"}
                            </p>
                            <div className="flex flex-wrap items-center gap-3 mt-2 text-sm text-muted-foreground">
                              <span className="flex items-center gap-1">
                                <Calendar className="h-4 w-4" />
                                {formatRelativeTime(meeting.scheduled_at)}
                              </span>
                              {meeting.duration_minutes && (
                                <span>{meeting.duration_minutes} min</span>
                              )}
                              <Badge
                                variant="outline"
                                className={cn("text-xs", statusColors[meeting.status] || "bg-muted text-muted-foreground")}
                              >
                                {meeting.status.replace(/_/g, " ")}
                              </Badge>
                            </div>
                          </div>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="ghost" size="icon" className="h-8 w-8">
                                <MoreVertical className="h-4 w-4" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuLabel>Actions</DropdownMenuLabel>
                              <DropdownMenuItem onClick={(e) => { e.stopPropagation(); window.location.href = `/dashboard/meetings/${meeting.id}`; }}>
                                <Eye className="h-4 w-4 mr-2" />
                                View Details
                              </DropdownMenuItem>
                              {meeting.transcript && (
                                <DropdownMenuItem onClick={(e) => { e.stopPropagation(); 
                                  const blob = new Blob([meeting.transcript?.full_text || ""], { type: "text/plain" });
                                  const url = URL.createObjectURL(blob);
                                  const a = document.createElement("a");
                                  a.href = url;
                                  a.download = `${meeting.title}-transcript.txt`;
                                  a.click();
                                  URL.revokeObjectURL(url);
                                }}>
                                  <Download className="h-4 w-4 mr-2" />
                                  Download Transcript
                                </DropdownMenuItem>
                              )}
                              <DropdownMenuSeparator />
                              {meeting.status === "ERROR" && (
                                <DropdownMenuItem onClick={(e) => { e.stopPropagation(); reprocessMutation.mutate(meeting.id); }}>
                                  <Play className="h-4 w-4 mr-2" />
                                  Reprocess
                                </DropdownMenuItem>
                              )}
                              <DropdownMenuItem className="text-destructive" onClick={(e) => { e.stopPropagation(); 
                                if (confirm("Are you sure you want to delete this meeting?")) {
                                  deleteMutation.mutate(meeting.id);
                                }
                              }}>
                                <Trash2 className="h-4 w-4 mr-2" />
                                Delete
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
              
              {data?.items.length === 0 && !isLoading && (
                <div className="text-center py-12 text-muted-foreground">
                  <Mic className="h-12 w-12 mx-auto mb-4 opacity-50" />
                  <p className="text-lg font-medium mb-2">No meetings found</p>
                  <p className="mb-4">Get started by uploading your first meeting recording</p>
                  <Button onClick={() => setShowUploadModal(true)}>
                    <Upload className="h-4 w-4 mr-2" />
                    Upload Meeting
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </DashboardLayout>
  );
}