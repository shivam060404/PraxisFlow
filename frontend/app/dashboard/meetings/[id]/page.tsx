"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { cn, formatRelativeTime, truncate } from "@/lib/utils";
import { api, type Meeting, type Transcript, type Utterance, type Task } from "@/lib/api";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Loader2, User, Clock, MessageSquare, Play, Pause, Volume2, Search, ChevronLeft, ChevronRight, Flag, CheckCircle, AlertTriangle, ArrowRightCircle, Gavel, Copy } from "lucide-react";
import { TaskCard } from "@/components/dashboard/task-card";

const typeIcons = {
  ACTION_ITEM: CheckCircle,
  DECISION: Gavel,
  FOLLOW_UP: ArrowRightCircle,
  BLOCKER: AlertTriangle,
};

function MeetingHeader({ meeting, transcript }: { meeting: Meeting; transcript?: Transcript }) {
  return (
    <Card className="mb-4">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <h1 className="text-2xl font-bold truncate">{meeting.title}</h1>
            <p className="text-muted-foreground mt-1">{meeting.description}</p>
            <div className="flex flex-wrap items-center gap-4 mt-3 text-sm text-muted-foreground">
              <span className="flex items-center gap-1">
                <Clock className="h-4 w-4" />
                {formatRelativeTime(meeting.scheduled_at)}
              </span>
              {meeting.duration_minutes && (
                <span className="flex items-center gap-1">
                  <Clock className="h-4 w-4" />
                  {meeting.duration_minutes} min
                </span>
              )}
              {transcript && (
                <span className="flex items-center gap-1">
                  <MessageSquare className="h-4 w-4" />
                  {transcript.word_count} words
                </span>
              )}
              <Badge variant="outline" className="capitalize">{meeting.status.toLowerCase().replace(/_/g, " ")}</Badge>
            </div>
          </div>
          <Button variant="outline" size="sm">
            <ChevronLeft className="h-4 w-4 mr-1" />
            Back to Board
          </Button>
        </div>
      </CardHeader>
    </Card>
  );
}

function TranscriptPlayer({ transcript, tasks, meetingId }: { transcript: Transcript; tasks: Task[]; meetingId: string }) {
  const [searchQuery, setSearchQuery] = React.useState("");
  const [speakerFilter, setSpeakerFilter] = React.useState<string>("all");
  const [playbackSpeed, setPlaybackSpeed] = React.useState(1);

  const speakers = React.useMemo(() => {
    const spkrs = new Set<string>();
    transcript.utterances?.forEach((u) => spkrs.add(u.speaker_label));
    return Array.from(spkrs).sort();
  }, [transcript.utterances]);

  const filteredUtterances = React.useMemo(() => {
    return transcript.utterances?.filter((u) => {
      const matchesSearch = !searchQuery || u.text.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesSpeaker = speakerFilter === "all" || u.speaker_label === speakerFilter;
      return matchesSearch && matchesSpeaker;
    }) || [];
  }, [transcript.utterances, searchQuery, speakerFilter]);

  const getRelatedTasks = (utterance: Utterance) => {
    return tasks.filter((task) => {
      const taskStart = task.transcript_word_start;
      const taskEnd = task.transcript_word_end;
      // This is approximate - in real app, you'd map utterance to word indices
      return utterance.text.toLowerCase().includes(task.source_quote.toLowerCase().slice(0, 20));
    });
  };

  const speakerColors: Record<string, string> = {};
  const colorPalette = [
    "bg-blue-500", "bg-green-500", "bg-purple-500", "bg-orange-500",
    "bg-pink-500", "bg-cyan-500", "bg-indigo-500", "bg-red-500",
  ];
  speakers.forEach((speaker, i) => {
    speakerColors[speaker] = colorPalette[i % colorPalette.length];
  });

  return (
    <div className="flex flex-col h-full">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 p-3 border-b bg-muted/30">
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm">
            <Play className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm">
            <Pause className="h-4 w-4" />
          </Button>
          <select
            value={playbackSpeed}
            onChange={(e) => setPlaybackSpeed(Number(e.target.value))}
            className="text-sm border rounded px-2 py-1 bg-background"
          >
            <option value={0.5}>0.5x</option>
            <option value={1}>1x</option>
            <option value={1.5}>1.5x</option>
            <option value={2}>2x</option>
          </select>
        </div>
        <Separator orientation="vertical" className="h-8 mx-2" />
        <div className="flex items-center gap-2">
          <Search className="h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search transcript..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-64"
            size="sm"
          />
          <Select value={speakerFilter} onValueChange={setSpeakerFilter} className="w-40">
            <SelectTrigger size="sm">
              <SelectValue placeholder="All speakers" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Speakers</SelectItem>
              {speakers.map((s) => (
                <SelectItem key={s} value={s}>{s}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Transcript */}
      <ScrollArea className="flex-1 overflow-y-auto">
        <div className="p-4 space-y-4">
          {filteredUtterances.map((utterance, index) => {
            const relatedTasks = getRelatedTasks(utterance);
            const IconComponent = typeIcons[relatedTasks[0]?.task_type as keyof typeof typeIcons] || MessageSquare;
            const hasTasks = relatedTasks.length > 0;

            return (
              <div
                key={utterance.id}
                className={cn(
                  "group relative p-3 rounded-lg border transition-colors",
                  hasTasks ? "bg-primary/5 border-primary/20" : "hover:bg-muted/30"
                )}
              >
                <div className="flex items-start gap-3">
                  <div className="flex-shrink-0 w-8 text-center text-xs text-muted-foreground pt-1">
                    {Math.floor(utterance.start_time_ms / 60000)}:{String(Math.floor((utterance.start_time_ms % 60000) / 1000)).padStart(2, "0")}
                  </div>
                  
                  <div className={cn(
                    "flex-1 min-w-0",
                    hasTasks && "pr-10"
                  )}>
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className={cn(
                          "px-2 py-0.5 rounded text-xs font-medium",
                          speakerColors[utterance.speaker_label] || "bg-muted"
                        )}
                      >
                        {utterance.speaker_label}
                      </span>
                      {utterance.confidence && (
                        <span className="text-xs text-muted-foreground">
                          {Math.round(utterance.confidence * 100)}%
                        </span>
                      )}
                    </div>
                    <p className="text-sm whitespace-pre-wrap">{utterance.text}</p>
                  </div>

                  {hasTasks && (
                    <div className="absolute right-3 top-3 flex flex-col gap-1">
                      {relatedTasks.slice(0, 3).map((task) => (
                        <Badge
                          key={task.id}
                          variant="outline"
                          className={cn(
                            "text-xs whitespace-nowrap",
                            task.verification_status === "NEEDS_REVIEW" && "border-amber-500 text-amber-700",
                            task.verification_status === "FAILED" && "border-red-500 text-red-700"
                          )}
                        >
                          <IconComponent className="h-3 w-3 mr-1" />
                          {truncate(task.title, 30)}
                        </Badge>
                      ))}
                      {relatedTasks.length > 3 && (
                        <Badge variant="outline" className="text-xs">
                          +{relatedTasks.length - 3} more
                        </Badge>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
          
          {filteredUtterances.length === 0 && (
            <div className="text-center py-12 text-muted-foreground">
              <Search className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p>No utterances match your search</p>
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

function ExtractedTasksPanel({ tasks, meetingId }: { tasks: Task[]; meetingId: string }) {
  const tasksByType = React.useMemo(() => {
    return tasks.reduce((acc, task) => {
      if (!acc[task.task_type]) acc[task.task_type] = [];
      acc[task.task_type].push(task);
      return acc;
    }, {} as Record<string, Task[]>);
  }, [tasks]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Extracted Tasks ({tasks.length})</h2>
        <Button variant="outline" size="sm">Export All</Button>
      </div>

      {Object.entries(tasksByType).map(([type, typeTasks]) => {
        const IconComponent = typeIcons[type as keyof typeof typeIcons] || MessageSquare;
        return (
          <div key={type} className="space-y-3">
            <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <IconComponent className="h-4 w-4" />
              <span className="capitalize">{type.toLowerCase().replace(/_/g, " ")}s</span>
              <Badge variant="secondary" className="ml-auto">{typeTasks.length}</Badge>
            </div>
            <div className="space-y-2">
              {typeTasks.map((task) => (
                <TaskCard key={task.id} task={task} onClick={() => {}} />
              ))}
            </div>
          </div>
        );
      })}

      {tasks.length === 0 && (
        <div className="text-center py-12 text-muted-foreground">
          <MessageSquare className="h-12 w-12 mx-auto mb-4 opacity-50" />
          <p>No tasks extracted from this meeting</p>
        </div>
      )}
    </div>
  );
}

export default function MeetingContextPage() {
  const params = useParams();
  const meetingId = params.id as string;

  const { data: meeting, isLoading: meetingLoading } = useQuery({
    queryKey: ["meeting", meetingId],
    queryFn: () => api.getMeeting(meetingId),
    enabled: !!meetingId,
  });

  const { data: transcript } = useQuery({
    queryKey: ["transcript", "meeting", meetingId],
    queryFn: () => api.getTranscript(meetingId),
    enabled: !!meetingId,
  });

  const { data: tasksResponse } = useQuery({
    queryKey: ["tasks", { meeting_id: meetingId }],
    queryFn: () => api.getTasks({ meeting_id: meetingId, page_size: 500 }),
    enabled: !!meetingId,
  });

  if (meetingLoading) {
    return (
      <DashboardLayout>
        <div className="flex h-[calc(100vh-4rem)] items-center justify-center">
          <Loader2 className="animate-spin h-8 w-8 text-primary" />
        </div>
      </DashboardLayout>
    );
  }

  if (!meeting) {
    return (
      <DashboardLayout>
        <div className="flex h-[calc(100vh-4rem)] items-center justify-center">
          <p className="text-muted-foreground">Meeting not found</p>
        </div>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <div className="h-[calc(100vh-4rem)] flex flex-col">
        <MeetingHeader meeting={meeting} transcript={transcript} />
        
        <div className="flex-1 flex overflow-hidden">
          {/* Left: Transcript Player */}
          <div className="w-1/2 border-r flex flex-col min-w-0">
            {transcript ? (
              <TranscriptPlayer transcript={transcript} tasks={tasksResponse?.items || []} meetingId={meetingId} />
            ) : (
              <div className="flex-1 flex items-center justify-center text-muted-foreground">
                <p>Transcript not available yet</p>
              </div>
            )}
          </div>

          {/* Right: Extracted Tasks & Summary */}
          <div className="w-1/2 flex flex-col min-w-0 overflow-hidden">
            <Tabs defaultValue="tasks" className="flex-1 flex flex-col">
              <TabsList className="border-b sticky top-0 bg-background z-10">
                <TabsTrigger value="tasks">Tasks</TabsTrigger>
                <TabsTrigger value="summary">Summary</TabsTrigger>
                <TabsTrigger value="topics">Topics</TabsTrigger>
              </TabsList>
              
              <TabsContent value="tasks" className="flex-1 overflow-auto p-4">
                <ExtractedTasksPanel tasks={tasksResponse?.items || []} meetingId={meetingId} />
              </TabsContent>
              
              <TabsContent value="summary" className="flex-1 overflow-auto p-4">
                <Card>
                  <CardHeader>
                    <CardTitle>Meeting Summary</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-muted-foreground">AI-generated summary will appear here after extraction completes.</p>
                  </CardContent>
                </Card>
              </TabsContent>
              
              <TabsContent value="topics" className="flex-1 overflow-auto p-4">
                <Card>
                  <CardHeader>
                    <CardTitle>Key Topics</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-muted-foreground">Key topics discussed in this meeting will appear here.</p>
                  </CardContent>
                </Card>
              </TabsContent>
            </Tabs>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}