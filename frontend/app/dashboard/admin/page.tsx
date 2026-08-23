"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Form, FormField, FormItem, FormLabel, FormControl, FormDescription, FormMessage } from "@/components/ui/form";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { Plus, RefreshCw, Shield, Users, Link2, Zap, Trash2, Edit, Eye, Download, AlertCircle, CheckCircle, XCircle, Settings, BarChart3, FileText, Stethoscope, Globe, Activity } from "lucide-react";
import { format } from "date-fns";
import { api } from "@/lib/api";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

const inviteUserSchema = z.object({
  email: z.string().email("Invalid email"),
  full_name: z.string().min(2, "Name too short"),
  role: z.enum(["tenant_admin", "team_lead", "member", "viewer", "api_service"]),
  department: z.string().optional(),
  team: z.string().optional(),
});

const integrationSchema = z.object({
  provider: z.string().min(1, "Required"),
  display_name: z.string().min(2, "Required"),
  config: z.record(z.unknown()),
  webhook_secret: z.string().optional(),
});

const integrationFormSchema = z.object({
  provider: z.string().min(1, "Provider is required"),
  display_name: z.string().min(2, "Display name is required"),
  config_json: z
    .string()
    .refine(
      (v) => {
        try {
          const parsed = JSON.parse(v || "{}");
          return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed);
        } catch {
          return false;
        }
      },
      { message: "Must be a valid JSON object" }
    ),
  webhook_secret: z.string().optional(),
});

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState("overview");
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<{
    tenant: any;
    usage: any;
    users: { users: any[]; total: number };
    integrations: any[];
    auditLogs: { logs: any[]; total: number };
    compliance: any;
    health: any;
    metrics: any;
  }>({
    tenant: null,
    usage: null,
    users: { users: [], total: 0 },
    integrations: [],
    auditLogs: { logs: [], total: 0 },
    compliance: null,
    health: null,
    metrics: null,
  });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [search, setSearch] = useState("");

  // Form states
  const [inviteDialogOpen, setInviteDialogOpen] = useState(false);
  const [integrationDialogOpen, setIntegrationDialogOpen] = useState(false);
  const [editIntegrationId, setEditIntegrationId] = useState<string | null>(null);
  const inviteForm = useForm<z.infer<typeof inviteUserSchema>>({
    resolver: zodResolver(inviteUserSchema),
    defaultValues: { email: "", full_name: "", role: "member", department: "", team: "" },
  });
  const integrationForm = useForm<z.infer<typeof integrationFormSchema>>({
    resolver: zodResolver(integrationFormSchema),
    defaultValues: { provider: "", display_name: "", config_json: "{}", webhook_secret: "" },
  });

  useEffect(() => {
    loadAdminData();
  }, [activeTab, page, search]);

  const loadAdminData = async () => {
    try {
      setLoading(true);
      if (activeTab === "overview" || activeTab === "users" || activeTab === "integrations") {
        const [tenant, usage, users, integrations] = await Promise.allSettled([
          api.getTenant(),
          api.getTenantUsage(),
          api.getTenantUsers({ page, page_size: pageSize, search }),
          api.getAdminIntegrations(),
        ]);
        setData(prev => ({
          ...prev,
          tenant: tenant.status === "fulfilled" ? tenant.value : null,
          usage: usage.status === "fulfilled" ? usage.value : null,
          users: users.status === "fulfilled" ? users.value : { users: [], total: 0 },
          integrations: integrations.status === "fulfilled" ? integrations.value : [],
        }));
      } else if (activeTab === "audit") {
        const audit = await api.getAdminAuditLogs({ page, page_size: pageSize, action: search });
        setData(prev => ({ ...prev, auditLogs: audit }));
      } else if (activeTab === "compliance") {
        const complianceRes = await api.getAdminComplianceStatus();
        setData(prev => ({ ...prev, compliance: complianceRes }));
      } else if (activeTab === "health") {
        const [health, metrics] = await Promise.allSettled([
          api.getAdminSystemHealth(),
          api.getAdminSystemMetrics(),
        ]);
        setData(prev => ({
          ...prev,
          health: health.status === "fulfilled" ? health.value : null,
          metrics: metrics.status === "fulfilled" ? metrics.value : null,
        }));
      }
    } catch (error) {
      console.error("Failed to load admin data:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleInviteSubmit = async (values: z.infer<typeof inviteUserSchema>) => {
    try {
      await api.inviteUser(values);
      setInviteDialogOpen(false);
      inviteForm.reset({ email: "", full_name: "", role: "member", department: "", team: "" });
      loadAdminData();
    } catch (error) {
      console.error("Failed to invite user:", error);
    }
  };

  const handleIntegrationSubmit = async (values: z.infer<typeof integrationFormSchema>) => {
    try {
      let parsedConfig: Record<string, unknown> = {};
      try {
        parsedConfig = JSON.parse(values.config_json || "{}");
      } catch {
        parsedConfig = {};
      }
      const payload: z.infer<typeof integrationSchema> = {
        provider: values.provider,
        display_name: values.display_name,
        config: parsedConfig,
        webhook_secret: values.webhook_secret || undefined,
      };
      if (editIntegrationId) {
        await api.updateAdminIntegration(editIntegrationId, payload);
      } else {
        await api.createAdminIntegration(payload);
      }
      setIntegrationDialogOpen(false);
      setEditIntegrationId(null);
      integrationForm.reset({ provider: "", display_name: "", config_json: "{}", webhook_secret: "" });
      loadAdminData();
    } catch (error) {
      console.error("Failed to save integration:", error);
    }
  };

  const handleDeleteIntegration = async (id: string) => {
    if (!confirm("Delete this integration? This cannot be undone.")) return;
    try {
      await api.deleteAdminIntegration(id);
      loadAdminData();
    } catch (error) {
      console.error("Failed to delete integration:", error);
    }
  };

  const handleTestIntegration = async (id: string) => {
    try {
      const result = await api.testAdminIntegration(id);
      alert(`Health check: ${result.healthy ? "Healthy" : "Unhealthy"} - ${result.message || ""}`);
    } catch (error) {
      console.error("Test failed:", error);
    }
  };

  const handleBulkAction = async (action: string, role?: string) => {
    // Would need selected user IDs from table
    console.log("Bulk action:", action, role);
  };

  const getStatusBadge = (status: string) => {
    const variants: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
      ACTIVE: "default",
      INACTIVE: "secondary",
      DELETED: "destructive",
      INVITED: "outline",
      PENDING: "outline",
    };
    return <Badge variant={variants[status] || "outline"}>{status}</Badge>;
  };

  const getHealthBadge = (status: string) => {
    const variants: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
      healthy: "default",
      unhealthy: "destructive",
      unknown: "outline",
    };
    return <Badge variant={variants[status] || "outline"}>{status}</Badge>;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Administration</h1>
          <p className="text-muted-foreground">Tenant management, integrations, and compliance</p>
        </div>
        <Button onClick={loadAdminData} variant="outline" disabled={loading}>
          <RefreshCw className="mr-2 h-4 w-4" /> Refresh
        </Button>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="integrations">Integrations</TabsTrigger>
          <TabsTrigger value="audit">Audit Logs</TabsTrigger>
          <TabsTrigger value="compliance">Compliance</TabsTrigger>
          <TabsTrigger value="health">System Health</TabsTrigger>
        </TabsList>

        {/* Overview Tab */}
        <TabsContent value="overview">
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Total Users</CardTitle>
                <Users className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{data.users?.total || 0}</div>
                <p className="text-xs text-muted-foreground">Active users</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Meetings</CardTitle>
                <Zap className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{data.usage?.meetings || 0}</div>
                <p className="text-xs text-muted-foreground">All time</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Tasks Extracted</CardTitle>
                <FileText className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{data.usage?.tasks || 0}</div>
                <p className="text-xs text-muted-foreground">All time</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Integrations</CardTitle>
                <Link2 className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{data.integrations?.length || 0}</div>
                <p className="text-xs text-muted-foreground">Configured</p>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 mt-4">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">AI Calls (Month)</CardTitle>
                <Activity className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{data.usage?.ai_calls_this_month || 0}</div>
                <p className="text-xs text-muted-foreground">API calls to LLM</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Tokens (Month)</CardTitle>
                <Zap className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{(data.usage?.tokens_this_month?.prompt || 0) + (data.usage?.tokens_this_month?.completion || 0).toLocaleString()}</div>
                <p className="text-xs text-muted-foreground">Prompt + Completion</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Plan</CardTitle>
                <Shield className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold capitalize">{data.tenant?.plan || "starter"}</div>
                <p className="text-xs text-muted-foreground">Data residency: {data.tenant?.attributes?.data_residency || "us"}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Status</CardTitle>
                <CheckCircle className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold capitalize">{data.tenant?.status || "active"}</div>
                <p className="text-xs text-muted-foreground">Tenant status</p>
              </CardContent>
            </Card>
          </div>

          {/* Quick Actions */}
          <Card>
            <CardHeader>
              <CardTitle>Quick Actions</CardTitle>
              <CardDescription>Common administrative tasks</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-4">
              <DialogTrigger asChild>
                <Button variant="outline" className="h-auto p-4 flex flex-col items-center gap-2">
                  <Plus className="h-6 w-6" />
                  <span className="text-sm">Invite User</span>
                </Button>
              </DialogTrigger>
              <Button variant="outline" className="h-auto p-4 flex flex-col items-center gap-2" onClick={() => setIntegrationDialogOpen(true)}>
                <Link2 className="h-6 w-6" />
                <span className="text-sm">Add Integration</span>
              </Button>
              <Button variant="outline" className="h-auto p-4 flex flex-col items-center gap-2" onClick={loadAdminData}>
                <RefreshCw className="h-6 w-6" />
                <span className="text-sm">Refresh Data</span>
              </Button>
              <Button variant="outline" className="h-auto p-4 flex flex-col items-center gap-2">
                <Download className="h-6 w-6" />
                <span className="text-sm">Export Data</span>
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Users Tab */}
        <TabsContent value="users">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-xl font-semibold">User Management</h2>
              <p className="text-muted-foreground">{data.users.total} total users</p>
            </div>
            <DialogTrigger asChild>
              <Button onClick={() => setInviteDialogOpen(true)}>
                <Plus className="mr-2 h-4 w-4" /> Invite User
              </Button>
            </DialogTrigger>
          </div>

          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>User</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Department</TableHead>
                    <TableHead>Team</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Last Login</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.users.users?.map((user) => (
                    <TableRow key={user.id}>
                      <TableCell>
                        <div>
                          <p className="font-medium">{user.full_name}</p>
                          <p className="text-xs text-muted-foreground font-mono">{user.id.slice(0, 8)}...</p>
                        </div>
                      </TableCell>
                      <TableCell>{user.email}</TableCell>
                      <TableCell><Badge variant={user.role === "tenant_admin" ? "default" : "secondary"}>{user.role}</Badge></TableCell>
                      <TableCell>{user.attributes?.department || "-"}</TableCell>
                      <TableCell>{user.attributes?.team || "-"}</TableCell>
                      <TableCell>{getStatusBadge(user.status || "active")}</TableCell>
                      <TableCell>{user.last_login ? format(new Date(user.last_login), "MMM d, yyyy") : "Never"}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Button variant="ghost" size="icon" onClick={() => { /* edit */ }}>
                            <Edit className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" onClick={() => { /* deactivate */ }}>
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {/* Pagination */}
          <div className="flex items-center justify-between mt-4">
            <span className="text-sm text-muted-foreground">
              Showing {(page - 1) * pageSize + 1} to {Math.min(page * pageSize, data.users.total)} of {data.users.total}
            </span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}>Previous</Button>
              <Button variant="outline" size="sm" onClick={() => setPage(p => p + 1)} disabled={page * pageSize >= data.users.total}>Next</Button>
            </div>
          </div>

          {/* Invite User Dialog */}
          <Dialog open={inviteDialogOpen} onOpenChange={setInviteDialogOpen}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Invite New User</DialogTitle>
              </DialogHeader>
              <Form {...inviteForm}>
                <form onSubmit={inviteForm.handleSubmit(handleInviteSubmit)} className="grid gap-4 py-4">
                  <FormField
                    control={inviteForm.control}
                    name="email"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Email</FormLabel>
                        <FormControl>
                          <Input placeholder="user@company.com" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={inviteForm.control}
                    name="full_name"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Full Name</FormLabel>
                        <FormControl>
                          <Input placeholder="John Doe" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={inviteForm.control}
                    name="role"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Role</FormLabel>
                        <Select onValueChange={field.onChange} defaultValue={field.value}>
                          <FormControl>
                            <SelectTrigger><SelectValue /></SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="member">Member</SelectItem>
                            <SelectItem value="team_lead">Team Lead</SelectItem>
                            <SelectItem value="tenant_admin">Tenant Admin</SelectItem>
                            <SelectItem value="viewer">Viewer</SelectItem>
                            <SelectItem value="api_service">API Service</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={inviteForm.control}
                    name="department"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Department (optional)</FormLabel>
                        <FormControl>
                          <Input placeholder="Engineering" {...field} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={inviteForm.control}
                    name="team"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Team (optional)</FormLabel>
                        <FormControl>
                          <Input placeholder="Platform Team" {...field} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                  <div className="flex justify-end gap-2 border-t pt-4">
                    <Button type="button" variant="outline" onClick={() => setInviteDialogOpen(false)}>Cancel</Button>
                    <Button type="submit">Send Invitation</Button>
                  </div>
                </form>
              </Form>
            </DialogContent>
          </Dialog>
        </TabsContent>

        {/* Integrations Tab */}
        <TabsContent value="integrations">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-xl font-semibold">Integrations</h2>
              <p className="text-muted-foreground">Configure external tool integrations</p>
            </div>
            <Button onClick={() => setIntegrationDialogOpen(true)}>
              <Plus className="mr-2 h-4 w-4" /> Add Integration
            </Button>
          </div>

          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Provider</TableHead>
                    <TableHead>Display Name</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Webhook</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.integrations?.map((integration) => (
                    <TableRow key={integration.id}>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Badge variant="outline">{integration.provider.toUpperCase()}</Badge>
                          <span className="font-medium">{integration.display_name}</span>
                        </div>
                      </TableCell>
                      <TableCell>{integration.display_name}</TableCell>
                      <TableCell>{getStatusBadge(integration.status)}</TableCell>
                      <TableCell>
                        {integration.webhook_secret ? (
                          <Badge variant="default">Configured</Badge>
                        ) : (
                          <Badge variant="outline">Not Set</Badge>
                        )}
                      </TableCell>
                      <TableCell>{format(new Date(integration.created_at), "MMM d, yyyy")}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Button variant="ghost" size="icon" onClick={() => handleTestIntegration(integration.id)}>
                            <Stethoscope className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" onClick={() => { setEditIntegrationId(integration.id); integrationForm.reset({ provider: integration.provider, display_name: integration.display_name, config_json: JSON.stringify(integration.config ?? {}, null, 2), webhook_secret: integration.webhook_secret ?? "" }); setIntegrationDialogOpen(true); }}>
                            <Edit className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" onClick={() => handleDeleteIntegration(integration.id)}>
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {/* Add/Edit Integration Dialog */}
          <Dialog open={integrationDialogOpen} onOpenChange={setIntegrationDialogOpen}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{editIntegrationId ? "Edit Integration" : "Add Integration"}</DialogTitle>
              </DialogHeader>
              <Form {...integrationForm}>
                <form onSubmit={integrationForm.handleSubmit(handleIntegrationSubmit)} className="grid gap-4 py-4">
                  <FormField
                    control={integrationForm.control}
                    name="provider"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Provider</FormLabel>
                        <Select onValueChange={field.onChange} defaultValue={field.value}>
                          <FormControl>
                            <SelectTrigger><SelectValue placeholder="Select provider" /></SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="jira">Jira</SelectItem>
                            <SelectItem value="asana">Asana</SelectItem>
                            <SelectItem value="linear">Linear</SelectItem>
                            <SelectItem value="slack">Slack</SelectItem>
                            <SelectItem value="teams">Microsoft Teams</SelectItem>
                            <SelectItem value="github">GitHub</SelectItem>
                            <SelectItem value="notion">Notion</SelectItem>
                            <SelectItem value="salesforce">Salesforce</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={integrationForm.control}
                    name="display_name"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Display Name</FormLabel>
                        <FormControl>
                          <Input placeholder="My Jira Instance" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={integrationForm.control}
                    name="config_json"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Configuration (JSON)</FormLabel>
                        <FormControl>
                          <Textarea
                            placeholder='{"domain": "company.atlassian.net", "email": "user@company.com"}'
                            value={field.value ?? "{}"}
                            onChange={(e) => field.onChange(e.target.value)}
                            rows={6}
                            className="font-mono text-sm"
                          />
                        </FormControl>
                        <FormDescription>Enter configuration as valid JSON</FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={integrationForm.control}
                    name="webhook_secret"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Webhook Secret (optional)</FormLabel>
                        <FormControl>
                          <Input type="password" placeholder="Secret for webhook verification" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <div className="flex justify-end gap-2 border-t pt-4">
                    <Button type="button" variant="outline" onClick={() => setIntegrationDialogOpen(false)}>Cancel</Button>
                    <Button type="submit">{editIntegrationId ? "Save Changes" : "Create Integration"}</Button>
                  </div>
                </form>
              </Form>
            </DialogContent>
          </Dialog>
        </TabsContent>

        {/* Audit Logs Tab */}
        <TabsContent value="audit">
          <Card>
            <CardHeader>
              <CardTitle>Audit Logs</CardTitle>
              <CardDescription>System-wide audit trail for compliance</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Timestamp</TableHead>
                      <TableHead>User</TableHead>
                      <TableHead>Action</TableHead>
                      <TableHead>Resource</TableHead>
                      <TableHead>IP Address</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.auditLogs.logs?.map((log) => (
                      <TableRow key={log.id}>
                        <TableCell>{format(new Date(log.created_at), "MMM d, yyyy HH:mm:ss")}</TableCell>
                        <TableCell>{log.user_id || "System"}</TableCell>
                        <TableCell><Badge variant="secondary">{log.action}</Badge></TableCell>
                        <TableCell>{log.resource_type}: {log.resource_id || "-"}</TableCell>
                        <TableCell className="font-mono text-xs">{log.ip_address || "-"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Compliance Tab */}
        <TabsContent value="compliance">
          <div className="grid gap-6">
            <Card>
              <CardHeader>
                <CardTitle>Compliance Status</CardTitle>
                <CardDescription>Real-time compliance posture across frameworks</CardDescription>
              </CardHeader>
              <CardContent>
                {data.compliance && (
                  <div className="grid gap-4 md:grid-cols-3">
                    <Card className="p-4 border-l-4 border-green-500">
                      <div className="flex items-center gap-3">
                        <Shield className="h-8 w-8 text-green-600" />
                        <div>
                          <h4 className="font-medium">EU AI Act</h4>
                          <p className="text-sm text-muted-foreground">{data.compliance.eu_ai_act?.status || "Compliant"}</p>
                        </div>
                      </div>
                    </Card>
                    <Card className="p-4 border-l-4 border-blue-500">
                      <div className="flex items-center gap-3">
                        <FileText className="h-8 w-8 text-blue-600" />
                        <div>
                          <h4 className="font-medium">GDPR</h4>
                          <p className="text-sm text-muted-foreground">{data.compliance.gdpr?.status || "Compliant"}</p>
                        </div>
                      </div>
                    </Card>
                    <Card className="p-4 border-l-4 border-purple-500">
                      <div className="flex items-center gap-3">
                        <Globe className="h-8 w-8 text-purple-600" />
                        <div>
                          <h4 className="font-medium">SOC 2 Type II</h4>
                          <p className="text-sm text-muted-foreground">{data.compliance.soc2?.status || "In Progress"}</p>
                        </div>
                      </div>
                    </Card>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* System Health Tab */}
        <TabsContent value="health">
          <div className="grid gap-6">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle>System Health</CardTitle>
                  <CardDescription>Real-time health status of all infrastructure components</CardDescription>
                </div>
                <Button variant="outline" onClick={loadAdminData}>
                  <RefreshCw className="mr-2 h-4 w-4" /> Refresh
                </Button>
              </CardHeader>
              <CardContent>
                {data.health && (
                  <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                    {Object.entries(data.health).map(([key, value]) => (
                      <div key={key} className={`p-4 rounded-lg border ${value === "healthy" ? "bg-green-50 border-green-200" : value === "unhealthy" ? "bg-red-50 border-red-200" : "bg-yellow-50 border-yellow-200"}`}>
                        <div className="flex items-center justify-between">
                          <h4 className="font-medium capitalize">{key.replace(/_/g, " ")}</h4>
                          {getHealthBadge(String(value))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>System Metrics</CardTitle>
                <CardDescription>Performance and usage metrics</CardDescription>
              </CardHeader>
              <CardContent>
                {data.metrics && (
                  <div className="grid gap-4 md:grid-cols-4">
                    <div className="p-4 bg-blue-50 rounded-lg">
                      <p className="text-sm text-muted-foreground">API Latency P95</p>
                      <p className="text-2xl font-bold">{data.metrics.api_latency_p95_ms || 0}ms</p>
                    </div>
                    <div className="p-4 bg-green-50 rounded-lg">
                      <p className="text-sm text-muted-foreground">Pipeline Completion</p>
                      <p className="text-2xl font-bold">{(data.metrics.pipeline_completion_rate || 0) * 100}%</p>
                    </div>
                    <div className="p-4 bg-purple-50 rounded-lg">
                      <p className="text-sm text-muted-foreground">Avg Pipeline Duration</p>
                      <p className="text-2xl font-bold">{data.metrics.avg_pipeline_duration_seconds || 0}s</p>
                    </div>
                    <div className="p-4 bg-orange-50 rounded-lg">
                      <p className="text-sm text-muted-foreground">Error Rate</p>
                      <p className="text-2xl font-bold">{data.metrics.error_rate || 0}%</p>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}