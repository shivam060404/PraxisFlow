"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, TrendingUp, TrendingDown, Users, Clock, CheckCircle, AlertTriangle, BarChart3, Target, Activity } from "lucide-react";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  ChartLegend,
  ChartLegendContent,
} from "@/components/ui/chart";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
} from "recharts";

const COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4"];

interface MetricsData {
  totalMeetings: number;
  totalTasksExtracted: number;
  verificationRate: number;
  avgTimeToSync: number;
  accuracyByWeek: Array<{ week: string; precision: number; recall: number; f1: number }>;
  funnelData: Array<{ stage: string; count: number }>;
  teamPerformance: Array<{
    teamMember: string;
    meetingsAttended: number;
    tasksAssigned: number;
    tasksCompleted: number;
    avgCompletionTime: number;
    overdueRate: number;
  }>;
}

function KPICard({ title, value, trend, period, description, inverseTrend = false, icon: Icon }: {
  title: string;
  value: string | number;
  trend?: number;
  period?: string;
  description?: string;
  inverseTrend?: boolean;
  icon: React.ComponentType<{ className?: string }>;
}) {
  const isPositive = trend !== undefined && trend > 0;
  const trendColor = inverseTrend ? (isPositive ? "text-red-600" : "text-green-600") : (isPositive ? "text-green-600" : "text-red-600");

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        <div className="flex items-center gap-2 mt-2">
          {trend !== undefined && (
            <span className={cn("text-xs font-medium", trendColor)}>
              {isPositive ? <TrendingUp className="h-3 w-3 inline mr-1" /> : <TrendingDown className="h-3 w-3 inline mr-1" />}
              {Math.abs(trend)}%
            </span>
          )}
          {period && <span className="text-xs text-muted-foreground">{period}</span>}
          {description && <p className="text-xs text-muted-foreground mt-1">{description}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function ExtractionAccuracyChart({ data }: { data: MetricsData["accuracyByWeek"] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Extraction Accuracy Trends</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[300px]">
          <ChartContainer
            config={{
              precision: { label: "Precision", color: COLORS[0] },
              recall: { label: "Recall", color: COLORS[1] },
              f1: { label: "F1 Score", color: COLORS[2] },
            }}
          >
            <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="colorPrecision" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={COLORS[0]} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={COLORS[0]} stopOpacity={0} />
                </linearGradient>
                <linearGradient id="colorRecall" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={COLORS[1]} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={COLORS[1]} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="week" />
              <YAxis domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
              <Tooltip formatter={(v) => [`${Math.round(v * 100)}%`, ""]} />
              <Legend />
              <Line type="monotone" dataKey="precision" stroke={COLORS[0]} strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="recall" stroke={COLORS[1]} strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="f1" stroke={COLORS[2]} strokeWidth={2} dot={false} />
            </LineChart>
          </ChartContainer>
        </div>
      </CardContent>
    </Card>
  );
}

function TaskCompletionFunnel({ stages, data }: { stages: string[]; data: MetricsData["funnelData"] }) {
  const maxCount = Math.max(...data.map((d) => d.count));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Task Completion Funnel</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {data.map((item, index) => (
            <div key={item.stage} className="space-y-1">
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium">{item.stage}</span>
                <span className="text-muted-foreground">{item.count}</span>
              </div>
              <div className="h-3 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary rounded-full transition-all duration-500"
                  style={{ width: `${maxCount > 0 ? (item.count / maxCount) * 100 : 0}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function TeamPerformanceTable({ data }: { data: MetricsData["teamPerformance"] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Team Performance</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="pb-2 font-medium">Team Member</th>
                <th className="pb-2 font-medium text-right">Meetings</th>
                <th className="pb-2 font-medium text-right">Assigned</th>
                <th className="pb-2 font-medium text-right">Completed</th>
                <th className="pb-2 font-medium text-right">Avg Time</th>
                <th className="pb-2 font-medium text-right">Overdue %</th>
              </tr>
            </thead>
            <tbody>
              {data.map((member, index) => (
                <tr key={member.teamMember} className="border-b last:border-0">
                  <td className="py-3 font-medium">{member.teamMember}</td>
                  <td className="py-3 text-right text-muted-foreground">{member.meetingsAttended}</td>
                  <td className="py-3 text-right text-muted-foreground">{member.tasksAssigned}</td>
                  <td className="py-3 text-right text-green-600 font-medium">{member.tasksCompleted}</td>
                  <td className="py-3 text-right text-muted-foreground">{member.avgCompletionTime}h</td>
                  <td className="py-3 text-right">
                    <Badge
                      variant={member.overdueRate > 20 ? "destructive" : member.overdueRate > 10 ? "outline" : "default"}
                      className="text-xs"
                    >
                      {member.overdueRate}%
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

export default function MetricsPage() {
  const { data: metrics, isLoading } = useQuery({
    queryKey: ["metrics"],
    queryFn: () => api.getMetrics(),
  });

  // Mock data for now since endpoint doesn't exist yet
  const mockMetrics: MetricsData = {
    totalMeetings: 142,
    totalTasksExtracted: 1250,
    verificationRate: 78,
    avgTimeToSync: 12,
    accuracyByWeek: [
      { week: "Week 1", precision: 0.72, recall: 0.68, f1: 0.70 },
      { week: "Week 2", precision: 0.75, recall: 0.71, f1: 0.73 },
      { week: "Week 3", precision: 0.78, recall: 0.74, f1: 0.76 },
      { week: "Week 4", precision: 0.81, recall: 0.77, f1: 0.79 },
    ],
    funnelData: [
      { stage: "Extracted", count: 1250 },
      { stage: "Verified", count: 975 },
      { stage: "Assigned", count: 850 },
      { stage: "Synced", count: 720 },
      { stage: "Completed", count: 580 },
    ],
    teamPerformance: [
      { teamMember: "Sarah Chen", meetingsAttended: 24, tasksAssigned: 45, tasksCompleted: 38, avgCompletionTime: 2.3, overdueRate: 5 },
      { teamMember: "Mike Johnson", meetingsAttended: 18, tasksAssigned: 32, tasksCompleted: 25, avgCompletionTime: 3.1, overdueRate: 12 },
      { teamMember: "Emily Davis", meetingsAttended: 31, tasksAssigned: 58, tasksCompleted: 52, avgCompletionTime: 1.8, overdueRate: 3 },
      { teamMember: "James Wilson", meetingsAttended: 15, tasksAssigned: 28, tasksCompleted: 19, avgCompletionTime: 4.2, overdueRate: 25 },
      { teamMember: "Lisa Anderson", meetingsAttended: 22, tasksAssigned: 41, tasksCompleted: 35, avgCompletionTime: 2.7, overdueRate: 8 },
    ],
  };

  const displayMetrics = metrics || mockMetrics;

  return (
    <DashboardLayout>
      <div className="h-[calc(100vh-4rem)] overflow-auto">
        <div className="p-4 space-y-6">
          {/* Header */}
          <div>
            <h1 className="text-2xl font-bold">Team Accountability Metrics</h1>
            <p className="text-sm text-muted-foreground">Track extraction accuracy, task completion, and team performance</p>
          </div>

          {/* KPI Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <KPICard
              title="Meetings Processed"
              value={displayMetrics.totalMeetings}
              trend={12}
              period="this week"
              icon={Activity}
            />
            <KPICard
              title="Tasks Extracted"
              value={displayMetrics.totalTasksExtracted}
              trend={8}
              period="this week"
              icon={Target}
            />
            <KPICard
              title="Verification Rate"
              value={`${displayMetrics.verificationRate}%`}
              trend={5}
              period="this week"
              description="AI-verified without human intervention"
              icon={CheckCircle}
            />
            <KPICard
              title="Avg. Time to Sync"
              value={`${displayMetrics.avgTimeToSync}m`}
              trend={-15}
              period="this week"
              description="From meeting end to Jira ticket"
              inverseTrend={true}
              icon={Clock}
            />
          </div>

          {/* Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ExtractionAccuracyChart data={displayMetrics.accuracyByWeek} />
            <TaskCompletionFunnel 
              stages={["Extracted", "Verified", "Assigned", "Synced", "Completed"]}
              data={displayMetrics.funnelData}
            />
          </div>

          {/* Team Performance Table */}
          <TeamPerformanceTable data={displayMetrics.teamPerformance} />
        </div>
      </div>
    </DashboardLayout>
  );
}