"use client";

import * as React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { api, type Integration } from "@/lib/api";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Loader2, Settings, Plug, Zap, TestTube, Save, Check, AlertCircle, X, ExternalLink, RefreshCw, MoreVertical, Trash2 } from "lucide-react";
import { Avatar, AvatarImage, AvatarFallback } from "@/components/ui/avatar";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { toast } from "sonner";

const integrationIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  jira: Plug,
  asana: Zap,
  linear: TestTube,
  slack: Settings,
};

const integrationColors: Record<string, string> = {
  jira: "bg-blue-100 text-blue-700",
  asana: "bg-orange-100 text-orange-700",
  linear: "bg-purple-100 text-purple-700",
  slack: "bg-green-100 text-green-700",
};

export default function SettingsPage() {
  const queryClient = useQueryClient();
  
  const { data: integrationsData, isLoading: integrationsLoading } = useQuery({
    queryKey: ["integrations"],
    queryFn: () => api.getIntegrations(),
  });

  const { data: userData } = useQuery({
    queryKey: ["user-profile"],
    queryFn: () => api.getCurrentUserProfile(),
  });

  const [activeTab, setActiveTab] = React.useState("integrations");
  const [showAddIntegration, setShowAddIntegration] = React.useState(false);
  const [newIntegration, setNewIntegration] = React.useState({
    provider: "jira",
    display_name: "",
    config: {} as Record<string, string>,
  });
  const [editingIntegration, setEditingIntegration] = React.useState<Integration | null>(null);
  const [editForm, setEditForm] = React.useState({
    display_name: "",
    config: {} as Record<string, string>,
    status: "ACTIVE",
  });

  const createIntegrationMutation = useMutation({
    mutationFn: (data: { provider: string; display_name: string; config: Record<string, unknown> }) => 
      api.createIntegration(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      setShowAddIntegration(false);
      setNewIntegration({ provider: "jira", display_name: "", config: {} });
      toast.success("Integration created successfully");
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to create integration");
    },
  });

  const updateIntegrationMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Integration> }) => 
      api.updateIntegration(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      setEditingIntegration(null);
      toast.success("Integration updated successfully");
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to update integration");
    },
  });

  const deleteIntegrationMutation = useMutation({
    mutationFn: (id: string) => api.deleteIntegration(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      toast.success("Integration deleted");
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to delete integration");
    },
  });

  const testIntegrationMutation = useMutation({
    mutationFn: (id: string) => api.testIntegration(id),
    onSuccess: (data, id) => {
      const integration = integrationsData?.items.find((i: Integration) => i.id === id);
      if (data.success) {
        toast.success(`${integration?.display_name || "Integration"} connected successfully!`);
      } else {
        toast.error(`${integration?.display_name || "Integration"} test failed: ${data.message}`);
      }
    },
    onError: (error: any, id) => {
      const integration = integrationsData?.items.find((i: Integration) => i.id === id);
      toast.error(`${integration?.display_name || "Integration"} test failed: ${error.response?.data?.detail || "Connection failed"}`);
    },
  });

  const getConfigFields = (provider: string) => {
    switch (provider) {
      case "jira":
        return [
          { key: "base_url", label: "Base URL", placeholder: "https://yourcompany.atlassian.net", required: true },
          { key: "email", label: "Email", placeholder: "user@company.com", required: true },
          { key: "api_token", label: "API Token", placeholder: "••••••••", type: "password", required: true },
          { key: "project_key", label: "Project Key", placeholder: "PROJ", required: true },
          { key: "issue_type", label: "Issue Type", placeholder: "Task", required: false },
        ];
      case "asana":
        return [
          { key: "access_token", label: "Personal Access Token", placeholder: "••••••••", type: "password", required: true },
          { key: "workspace_gid", label: "Workspace GID", placeholder: "123456789", required: true },
          { key: "project_gid", label: "Project GID", placeholder: "123456789", required: true },
        ];
      case "linear":
        return [
          { key: "api_key", label: "API Key", placeholder: "lin_api_••••••••", type: "password", required: true },
          { key: "team_id", label: "Team ID", placeholder: "team-uuid", required: true },
        ];
      case "slack":
        return [
          { key: "bot_token", label: "Bot Token", placeholder: "xoxb-••••••••", type: "password", required: true },
          { key: "signing_secret", label: "Signing Secret", placeholder: "••••••••", type: "password", required: true },
          { key: "default_channel", label: "Default Channel", placeholder: "#general", required: false },
        ];
      default:
        return [];
    }
  };

  const handleConfigChange = (provider: string, key: string, value: string) => {
    if (editingIntegration) {
      setEditForm(prev => ({
        ...prev,
        config: { ...prev.config, [key]: value },
      }));
    } else {
      setNewIntegration(prev => ({
        ...prev,
        config: { ...prev.config, [key]: value },
      }));
    }
  };

  const startEditing = (integration: Integration) => {
    setEditingIntegration(integration);
    setEditForm({
      display_name: integration.display_name,
      config: integration.config as Record<string, string>,
      status: integration.status,
    });
  };

  const cancelEditing = () => {
    setEditingIntegration(null);
    setEditForm({ display_name: "", config: {}, status: "ACTIVE" });
  };

  const saveIntegration = (id: string) => {
    updateIntegrationMutation.mutate({ id, data: editForm });
  };

  const deleteIntegration = (id: string) => {
    if (confirm("Are you sure you want to delete this integration?")) {
      deleteIntegrationMutation.mutate(id);
    }
  };

  const testIntegration = (id: string) => {
    testIntegrationMutation.mutate(id);
  };

  return (
    <DashboardLayout>
      <div className="h-[calc(100vh-4rem)] flex flex-col">
        {/* Header */}
        <div className="p-4 border-b">
          <h1 className="text-2xl font-bold">Settings</h1>
          <p className="text-sm text-muted-foreground">Manage your workspace settings and integrations</p>
        </div>

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 overflow-auto">
          <TabsList className="grid w-full grid-cols-4 p-2 border-b">
            <TabsTrigger value="integrations">Integrations</TabsTrigger>
            <TabsTrigger value="profile">Profile</TabsTrigger>
            <TabsTrigger value="notifications">Notifications</TabsTrigger>
            <TabsTrigger value="billing">Billing</TabsTrigger>
          </TabsList>

          {/* Integrations Tab */}
          <TabsContent value="integrations" className="p-4 space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold">External Integrations</h2>
                <p className="text-sm text-muted-foreground">Connect your favorite tools to sync tasks automatically</p>
              </div>
              <Dialog open={showAddIntegration} onOpenChange={setShowAddIntegration}>
                <DialogTrigger asChild>
                  <Button>
                    <ExternalLink className="h-4 w-4 mr-2" />
                    Add Integration
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
                  <DialogHeader>
                    <DialogTitle>Add New Integration</DialogTitle>
                  </DialogHeader>
                  <div className="py-4 space-y-4">
                    <div className="grid grid-cols-4 items-center gap-4">
                      <Label htmlFor="provider" className="text-right">Provider</Label>
                      <Select value={newIntegration.provider} onValueChange={(value) => setNewIntegration(prev => ({ ...prev, provider: value, config: {} }))}>
                        <SelectTrigger className="col-span-3">
                          <SelectValue placeholder="Select provider" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="jira">Jira</SelectItem>
                          <SelectItem value="asana">Asana</SelectItem>
                          <SelectItem value="linear">Linear</SelectItem>
                          <SelectItem value="slack">Slack</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="grid grid-cols-4 items-center gap-4">
                      <Label htmlFor="display_name" className="text-right">Display Name</Label>
                      <Input
                        id="display_name"
                        value={newIntegration.display_name}
                        onChange={(e) => setNewIntegration(prev => ({ ...prev, display_name: e.target.value }))}
                        className="col-span-3"
                        placeholder="My Jira Workspace"
                        required
                      />
                    </div>
                    <Separator />
                    <div className="space-y-3">
                      {getConfigFields(newIntegration.provider).map((field) => (
                        <div key={field.key} className="grid grid-cols-4 items-center gap-4">
                          <Label htmlFor={field.key} className="text-right">
                            {field.label} {field.required && <span className="text-destructive">*</span>}
                          </Label>
                          <Input
                            id={field.key}
                            type={field.type || "text"}
                            placeholder={field.placeholder}
                            value={newIntegration.config[field.key] || ""}
                            onChange={(e) => handleConfigChange(newIntegration.provider, field.key, e.target.value)}
                            className="col-span-3"
                            required={field.required}
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                  <DialogFooter>
                    <Button type="button" variant="outline" onClick={() => setShowAddIntegration(false)}>
                      Cancel
                    </Button>
                    <Button type="submit" onClick={() => createIntegrationMutation.mutate(newIntegration)} disabled={createIntegrationMutation.isPending}>
                      {createIntegrationMutation.isPending ? "Adding..." : "Add Integration"}
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>

            {integrationsLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="animate-spin h-8 w-8 text-primary" />
              </div>
            ) : (
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {integrationsData?.items.map((integration: Integration) => (
                  <Card key={integration.id} className={editingIntegration?.id === integration.id ? "ring-2 ring-primary" : ""}>
                    <CardHeader className="pb-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <div className={cn("p-2 rounded-lg", integrationColors[integration.provider])}>
                            {React.createElement(integrationIcons[integration.provider] ?? Plug, { className: "h-5 w-5" })}
                          </div>
                          <div>
                            <h3 className="font-semibold">{integration.display_name}</h3>
                            <Badge variant="outline" className={cn("text-xs", integrationColors[integration.provider])}>
                              {integration.provider.toUpperCase()}
                            </Badge>
                          </div>
                        </div>
                        {editingIntegration?.id === integration.id ? (
                          <div className="flex gap-2">
                            <Button variant="outline" size="sm" onClick={cancelEditing}>
                              <X className="h-4 w-4" />
                            </Button>
                            <Button size="sm" onClick={() => saveIntegration(integration.id)} disabled={updateIntegrationMutation.isPending}>
                              <Save className="h-4 w-4 mr-1" />
                              Save
                            </Button>
                          </div>
                        ) : (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="ghost" size="icon" className="h-8 w-8">
                                <MoreVertical className="h-4 w-4" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuLabel>Actions</DropdownMenuLabel>
                              <DropdownMenuItem onClick={() => startEditing(integration)}>
                                <Settings className="h-4 w-4 mr-2" />
                                Edit
                              </DropdownMenuItem>
                              <DropdownMenuItem onClick={() => testIntegration(integration.id)} disabled={testIntegrationMutation.isPending}>
                                <RefreshCw className="h-4 w-4 mr-2" />
                                {testIntegrationMutation.isPending && testIntegrationMutation.variables === integration.id ? "Testing..." : "Test Connection"}
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem className="text-destructive" onClick={() => deleteIntegration(integration.id)}>
                                <Trash2 className="h-4 w-4 mr-2" />
                                Delete
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        )}
                      </div>
                    </CardHeader>
                    <CardContent className={editingIntegration?.id === integration.id ? "pt-4" : "pt-0"}>
                      {editingIntegration?.id === integration.id ? (
                        <div className="space-y-4">
                          <div className="grid grid-cols-4 items-center gap-4">
                            <Label className="text-right">Display Name</Label>
                            <Input
                              value={editForm.display_name}
                              onChange={(e) => setEditForm(prev => ({ ...prev, display_name: e.target.value }))}
                              className="col-span-3"
                            />
                          </div>
                          <Separator />
                          <div className="grid grid-cols-4 items-center gap-4">
                            <Label className="text-right">Status</Label>
                            <Select value={editForm.status} onValueChange={(value) => setEditForm(prev => ({ ...prev, status: value }))}>
                              <SelectTrigger className="col-span-3 w-full">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="ACTIVE">Active</SelectItem>
                                <SelectItem value="INACTIVE">Inactive</SelectItem>
                                <SelectItem value="ERROR">Error</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                          {getConfigFields(integration.provider).map((field) => (
                            <div key={field.key} className="grid grid-cols-4 items-center gap-4">
                              <Label htmlFor={`${integration.id}-${field.key}`} className="text-right">
                                {field.label} {field.required && <span className="text-destructive">*</span>}
                              </Label>
                              <Input
                                id={`${integration.id}-${field.key}`}
                                type={field.type || "text"}
                                placeholder={field.placeholder}
                                value={editForm.config[field.key] || ""}
                                onChange={(e) => handleConfigChange(integration.provider, field.key, e.target.value)}
                                className="col-span-3"
                              />
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="space-y-2 text-sm text-muted-foreground">
                          <p><strong>Status:</strong> {integration.status}</p>
                          {integration.config.base_url && <p><strong>URL:</strong> {integration.config.base_url}</p>}
                          {integration.config.email && <p><strong>Email:</strong> {integration.config.email}</p>}
                          {integration.config.workspace_gid && <p><strong>Workspace:</strong> {integration.config.workspace_gid}</p>}
                          {integration.config.team_id && <p><strong>Team:</strong> {integration.config.team_id}</p>}
                          <p className="mt-2"><strong>Created:</strong> {new Date(integration.created_at).toLocaleDateString()}</p>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                ))}
                
                {(!integrationsData?.items || integrationsData.items.length === 0) && !integrationsLoading && (
                  <div className="col-span-full text-center py-12">
                    <Plug className="h-12 w-12 mx-auto mb-4 opacity-50" />
                    <p className="text-lg font-medium mb-2">No integrations configured</p>
                    <p className="mb-4 text-muted-foreground">Connect your tools to automatically sync tasks</p>
                    <Button onClick={() => setShowAddIntegration(true)}>
                      <ExternalLink className="h-4 w-4 mr-2" />
                      Add Your First Integration
                    </Button>
                  </div>
                )}
              </div>
            )}
          </TabsContent>

          {/* Profile Tab */}
          <TabsContent value="profile" className="p-4 space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Profile Settings</CardTitle>
                <CardDescription>Manage your personal information</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="max-w-md space-y-4">
                  <div className="flex items-center gap-4">
                    <Avatar className="h-20 w-20">
                      <AvatarImage src={userData?.avatar_url || ""} alt={userData?.full_name || ""} />
                      <AvatarFallback className="text-2xl">
                        {userData?.full_name?.charAt(0).toUpperCase()}
                      </AvatarFallback>
                    </Avatar>
                    <div>
                      <h3 className="text-lg font-semibold">{userData?.full_name}</h3>
                      <p className="text-muted-foreground">{userData?.email}</p>
                      <Badge variant="outline" className="mt-1">{userData?.role}</Badge>
                    </div>
                  </div>
                  <Separator />
                  <div className="grid grid-cols-4 items-center gap-4">
                    <Label htmlFor="full_name" className="text-right">Full Name</Label>
                    <Input
                      id="full_name"
                      defaultValue={userData?.full_name}
                      className="col-span-3"
                    />
                  </div>
                  <div className="grid grid-cols-4 items-center gap-4">
                    <Label htmlFor="email" className="text-right">Email</Label>
                    <Input
                      id="email"
                      type="email"
                      defaultValue={userData?.email}
                      className="col-span-3"
                      disabled
                    />
                  </div>
                  <div className="grid grid-cols-4 items-center gap-4">
                    <Label htmlFor="role" className="text-right">Role</Label>
                    <Input
                      id="role"
                      defaultValue={userData?.role}
                      className="col-span-3"
                      disabled
                    />
                  </div>
                  <Button>Save Changes</Button>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Notifications Tab */}
          <TabsContent value="notifications" className="p-4 space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Notification Preferences</CardTitle>
                <CardDescription>Choose how you want to be notified</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {[
                  { id: "task_assigned", label: "Task Assigned", description: "When a task is assigned to you" },
                  { id: "task_due_soon", label: "Task Due Soon", description: "Reminder 24 hours before deadline" },
                  { id: "task_overdue", label: "Task Overdue", description: "When a task passes its deadline" },
                  { id: "meeting_processed", label: "Meeting Processed", description: "When a meeting finishes processing" },
                  { id: "verification_needed", label: "Verification Needed", description: "When a task needs your review" },
                  { id: "sync_complete", label: "Sync Complete", description: "When tasks sync to external tools" },
                ].map((notification) => (
                  <div key={notification.id} className="flex items-center justify-between p-3 border rounded-lg">
                    <div className="flex-1">
                      <p className="font-medium">{notification.label}</p>
                      <p className="text-sm text-muted-foreground">{notification.description}</p>
                    </div>
                    <div className="flex items-center gap-4">
                      <Label className="flex items-center gap-2 cursor-pointer">
                        <span>Email</span>
                        <Switch defaultChecked />
                      </Label>
                      <Label className="flex items-center gap-2 cursor-pointer">
                        <span>In-App</span>
                        <Switch defaultChecked />
                      </Label>
                      <Label className="flex items-center gap-2 cursor-pointer">
                        <span>Slack</span>
                        <Switch defaultChecked={false} />
                      </Label>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          </TabsContent>

          {/* Billing Tab */}
          <TabsContent value="billing" className="p-4 space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Billing & Subscription</CardTitle>
                <CardDescription>Manage your plan and billing information</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="max-w-2xl space-y-6">
                  <div className="p-4 border rounded-lg bg-muted/30">
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="font-semibold">Current Plan: <span className="text-primary">Enterprise</span></h3>
                        <p className="text-sm text-muted-foreground">Unlimited meetings, advanced AI, priority support</p>
                      </div>
                      <Badge variant="secondary" className="text-sm">Active</Badge>
                    </div>
                  </div>
                  <div className="grid gap-4 md:grid-cols-3">
                    <div className="p-4 border rounded-lg">
                      <h4 className="font-medium mb-2">Meetings This Month</h4>
                      <p className="text-3xl font-bold text-primary">142 / ∞</p>
                    </div>
                    <div className="p-4 border rounded-lg">
                      <h4 className="font-medium mb-2">Storage Used</h4>
                      <p className="text-3xl font-bold text-primary">12.4 GB / 100 GB</p>
                    </div>
                    <div className="p-4 border rounded-lg">
                      <h4 className="font-medium mb-2">Team Members</h4>
                      <p className="text-3xl font-bold text-primary">24 / 50</p>
                    </div>
                  </div>
                  <Button variant="outline">Manage Subscription</Button>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </DashboardLayout>
  );
}