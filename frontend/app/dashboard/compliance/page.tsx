"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { Download, RefreshCw, AlertCircle, CheckCircle, XCircle, Clock, FileText, Shield, Users, Database, Activity } from "lucide-react";
import { format } from "date-fns";
import { api, type DataSubjectRequestType } from "@/lib/api";

const getStatusBadge = (status: string) => {
  const variants: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
    completed: "default",
    pending: "secondary",
    processing: "outline",
    failed: "destructive",
    in_progress: "outline",
  };
  return <Badge variant={variants[status] || "secondary"}>{status}</Badge>;
};

export default function CompliancePage() {
  const [activeTab, setActiveTab] = useState("overview");
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<{
    euAiAct?: any;
    gdpr?: any;
    modelCards?: any;
    auditLogs?: any[];
    exports?: any[];
    dsrRequests?: any[];
  }>({});

  const [dsrForm, setDsrForm] = useState<{
    request_type: DataSubjectRequestType;
    data_subject_email: string;
    reason: string;
    specific_data_categories: string[];
  }>({
    request_type: "access",
    data_subject_email: "",
    reason: "",
    specific_data_categories: [],
  });
  const [dsrLoading, setDsrLoading] = useState(false);

  const [exportForm, setExportForm] = useState<{
    format: "json" | "csv" | "pdf";
    include_audit_logs: boolean;
    include_ai_decisions: boolean;
    date_from: string;
    date_to: string;
  }>({
    format: "json",
    include_audit_logs: true,
    include_ai_decisions: true,
    date_from: "",
    date_to: "",
  });
  const [exportLoading, setExportLoading] = useState(false);

  useEffect(() => {
    loadComplianceData();
  }, []);

  const loadComplianceData = async () => {
    try {
      setLoading(true);
      const [euAiAct, gdpr, modelCards, auditLogs, exports, dsrRequests] = await Promise.allSettled([
        api.getEUAIActStatus(),
        api.getGDPRStatus(),
        api.getModelCards(),
        api.getAIAuditLogs({ limit: 50 }),
        Promise.resolve([]),
        api.getDataSubjectRequests(),
      ]);

      setData({
        euAiAct: euAiAct.status === "fulfilled" ? euAiAct.value : null,
        gdpr: gdpr.status === "fulfilled" ? gdpr.value : null,
        modelCards: modelCards.status === "fulfilled" ? modelCards.value : null,
        auditLogs: auditLogs.status === "fulfilled" ? auditLogs.value : [],
        exports: exports.status === "fulfilled" ? exports.value : [],
        dsrRequests: dsrRequests.status === "fulfilled" ? dsrRequests.value : [],
      });
    } catch (error) {
      console.error("Failed to load compliance data:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleDsrSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setDsrLoading(true);
    try {
      await api.createDataSubjectRequest(dsrForm);
      await loadComplianceData();
      setDsrForm({ request_type: "access", data_subject_email: "", reason: "", specific_data_categories: [] });
    } catch (error) {
      console.error("Failed to create DSR:", error);
    } finally {
      setDsrLoading(false);
    }
  };

  const handleExportSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setExportLoading(true);
    try {
      await api.exportTenantData(exportForm);
      await loadComplianceData();
    } catch (error) {
      console.error("Failed to create export:", error);
    } finally {
      setExportLoading(false);
    }
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
          <h1 className="text-3xl font-bold">Compliance & Governance</h1>
          <p className="text-muted-foreground">
            EU AI Act, GDPR, SOC 2, and ISO 27001 compliance management
          </p>
        </div>
        <Button variant="outline" onClick={loadComplianceData}>
          <RefreshCw className="mr-2 h-4 w-4" /> Refresh
        </Button>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList className="grid w-full grid-cols-5">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="eu-ai-act">EU AI Act</TabsTrigger>
          <TabsTrigger value="gdpr">GDPR</TabsTrigger>
          <TabsTrigger value="models">Model Cards</TabsTrigger>
          <TabsTrigger value="exports">Exports</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">EU AI Act</CardTitle>
                <Shield className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {data.euAiAct?.overall_compliant ? "Compliant" : "Non-Compliant"}
                </div>
                <p className="text-xs text-muted-foreground">
                  {data.euAiAct?.last_assessment ? `Last: ${format(new Date(data.euAiAct.last_assessment), "MMM d, yyyy")}` : "Not assessed"}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">GDPR</CardTitle>
                <Database className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {data.gdpr?.overall_compliant ? "Compliant" : "Non-Compliant"}
                </div>
                <p className="text-xs text-muted-foreground">
                  DSRs: {data.dsrRequests?.length || 0} pending
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">AI Models</CardTitle>
                <Activity className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{data.modelCards?.models?.length || 0}</div>
                <p className="text-xs text-muted-foreground">Documented models</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Audit Logs (30d)</CardTitle>
                <FileText className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{data.auditLogs?.length || 0}</div>
                <p className="text-xs text-muted-foreground">AI decisions logged</p>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Data Subject Requests</CardTitle>
                <CardDescription>GDPR Articles 15-22 requests</CardDescription>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleDsrSubmit} className="space-y-4 mb-6 p-4 bg-muted/50 rounded-lg">
                  <h4 className="font-medium">Create New DSR</h4>
                  <div className="grid gap-2 md:grid-cols-2">
                    <Select value={dsrForm.request_type} onValueChange={(v) => setDsrForm({ ...dsrForm, request_type: v as DataSubjectRequestType })}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="access">Access (Art. 15)</SelectItem>
                        <SelectItem value="rectification">Rectification (Art. 16)</SelectItem>
                        <SelectItem value="erasure">Erasure (Art. 17)</SelectItem>
                        <SelectItem value="restriction">Restriction (Art. 18)</SelectItem>
                        <SelectItem value="portability">Portability (Art. 20)</SelectItem>
                        <SelectItem value="objection">Objection (Art. 21)</SelectItem>
                      </SelectContent>
                    </Select>
                    <Input
                      placeholder="Data Subject Email"
                      value={dsrForm.data_subject_email}
                      onChange={(e) => setDsrForm({ ...dsrForm, data_subject_email: e.target.value })}
                    />
                  </div>
                  <Textarea
                    placeholder="Reason for request"
                    value={dsrForm.reason}
                    onChange={(e) => setDsrForm({ ...dsrForm, reason: e.target.value })}
                    rows={2}
                  />
                  <Button type="submit" disabled={dsrLoading}>
                    {dsrLoading ? "Creating..." : "Create Request"}
                  </Button>
                </form>

                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Type</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Created</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.dsrRequests?.map((req) => (
                      <TableRow key={req.id}>
                        <TableCell>
                          <Badge variant="secondary">{req.request_type}</Badge>
                        </TableCell>
                        <TableCell>{req.data_subject_email}</TableCell>
                        <TableCell>{getStatusBadge(req.status)}</TableCell>
                        <TableCell>{format(new Date(req.created_at), "MMM d, yyyy")}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Recent AI Audit Logs</CardTitle>
                <CardDescription>EU AI Act Article 12 record-keeping</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Time</TableHead>
                        <TableHead>Node</TableHead>
                        <TableHead>Model</TableHead>
                        <TableHead>Confidence</TableHead>
                        <TableHead>Cost</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.auditLogs?.slice(0, 10).map((log) => (
                        <TableRow key={log.id}>
                          <TableCell>{format(new Date(log.timestamp), "MMM d, HH:mm")}</TableCell>
                          <TableCell>{log.pipeline_node}</TableCell>
                          <TableCell className="font-mono text-xs">{log.model}</TableCell>
                          <TableCell>{log.confidence_score ? `${(log.confidence_score * 100).toFixed(0)}%` : "N/A"}</TableCell>
                          <TableCell>${log.cost_usd?.toFixed(4) || "0.0000"}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="eu-ai-act">
          <Card>
            <CardHeader>
              <CardTitle>EU AI Act Compliance Status</CardTitle>
              <CardDescription>High-risk AI system requirements (Articles 9-15)</CardDescription>
            </CardHeader>
            <CardContent>
              {data.euAiAct ? (
                <div className="space-y-4">
                  <div className="flex items-center gap-4 p-4 bg-green-50 rounded-lg">
                    <CheckCircle className="h-8 w-8 text-green-600" />
                    <div>
                      <h4 className="font-medium">Overall Status: Compliant</h4>
                      <p className="text-sm text-muted-foreground">Last assessment: {data.euAiAct.last_assessment ? format(new Date(data.euAiAct.last_assessment), "MMMM d, yyyy") : "N/A"}</p>
                    </div>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                    {[
                      { key: "risk_management_system", label: "Risk Management (Art. 9)", icon: Shield },
                      { key: "data_governance", label: "Data Governance (Art. 10)", icon: Database },
                      { key: "technical_documentation", label: "Technical Docs (Art. 11)", icon: FileText },
                      { key: "record_keeping", label: "Record Keeping (Art. 12)", icon: Database },
                      { key: "transparency", label: "Transparency (Art. 13)", icon: Activity },
                      { key: "human_oversight", label: "Human Oversight (Art. 14)", icon: Users },
                      { key: "accuracy_robustness", label: "Accuracy & Robustness (Art. 15)", icon: Shield },
                      { key: "cybersecurity", label: "Cybersecurity (Art. 15)", icon: Shield },
                    ].map((item) => (
                      <Card key={item.key} className="p-4">
                        <div className="flex items-center gap-3">
                          <item.icon className={`h-5 w-5 ${data.euAiAct[item.key] ? "text-green-600" : "text-red-600"}`} />
                          <div>
                            <p className="font-medium">{item.label}</p>
                            <p className="text-sm text-muted-foreground">
                              {data.euAiAct[item.key] ? "Implemented" : "Not Implemented"}
                            </p>
                          </div>
                        </div>
                      </Card>
                    ))}
                  </div>
                </div>
              ) : (
                <p>Loading EU AI Act status...</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="gdpr">
          <Card>
            <CardHeader>
              <CardTitle>GDPR Compliance Status</CardTitle>
              <CardDescription>Data protection requirements (Articles 5-32)</CardDescription>
            </CardHeader>
            <CardContent>
              {data.gdpr ? (
                <div className="space-y-4">
                  <div className="flex items-center gap-4 p-4 bg-green-50 rounded-lg">
                    <CheckCircle className="h-8 w-8 text-green-600" />
                    <div>
                      <h4 className="font-medium">Overall Status: Compliant</h4>
                    </div>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                    {[
                      { key: "lawful_basis_documented", label: "Lawful Basis Documented (Art. 6)", icon: FileText },
                      { key: "dpia_completed", label: "DPIA Completed (Art. 35)", icon: Shield },
                      { key: "data_processing_agreements", label: "DPAs Signed (Art. 28)", icon: FileText },
                      { key: "data_subject_rights_process", label: "DSR Process (Art. 15-22)", icon: Users },
                      { key: "breach_notification_process", label: "Breach Notification (Art. 33)", icon: AlertCircle },
                      { key: "data_retention_policy", label: "Retention Policy (Art. 5)", icon: Clock },
                      { key: "cross_border_transfers", label: "Cross-Border Transfers (Art. 44)", icon: Database },
                      { key: "sccs_in_place", label: "SCCs in Place (Art. 46)", icon: FileText },
                    ].map((item) => (
                      <Card key={item.key} className="p-4">
                        <div className="flex items-center gap-3">
                          <item.icon className={`h-5 w-5 ${data.gdpr[item.key] ? "text-green-600" : "text-red-600"}`} />
                          <div>
                            <p className="font-medium">{item.label}</p>
                            <p className="text-sm text-muted-foreground">
                              {data.gdpr[item.key] ? "In Place" : "Missing"}
                            </p>
                          </div>
                        </div>
                      </Card>
                    ))}
                  </div>
                </div>
              ) : (
                <p>Loading GDPR status...</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="models">
          <Card>
            <CardHeader>
              <CardTitle>AI Model Cards</CardTitle>
              <CardDescription>Technical documentation for each AI model (EU AI Act Art. 11)</CardDescription>
            </CardHeader>
            <CardContent>
              {data.modelCards?.models?.map((model: any) => (
                <Card key={model.name} className="border-l-4 border-primary my-4">
                  <CardHeader>
                    <div className="flex items-start justify-between">
                      <div>
                        <CardTitle className="flex items-center gap-2">
                          {model.name}
                          <Badge variant="secondary">{model.provider}</Badge>
                          <Badge variant="outline">{model.type}</Badge>
                        </CardTitle>
                        <CardDescription>{model.purpose}</CardDescription>
                      </div>
                      <Badge variant={model.performance_metrics?.faithfulness > 0.85 ? "default" : "secondary"}>
                        Faithfulness: {(model.performance_metrics?.faithfulness * 100).toFixed(0)}%
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="grid gap-4 md:grid-cols-3">
                      <div>
                        <h4 className="font-medium text-sm">Limitations</h4>
                        <p className="text-sm text-muted-foreground">{model.limitations}</p>
                      </div>
                      <div>
                        <h4 className="font-medium text-sm">Intended Use</h4>
                        <p className="text-sm text-muted-foreground">{model.intended_use}</p>
                      </div>
                      <div>
                        <h4 className="font-medium text-sm">Not Intended For</h4>
                        <p className="text-sm text-muted-foreground">{model.not_intended_for}</p>
                      </div>
                    </div>
                    <div className="grid gap-4 md:grid-cols-3">
                      <div>
                        <h4 className="font-medium text-sm">Data Governance</h4>
                        <p className="text-sm text-muted-foreground">{model.data_governance}</p>
                      </div>
                      <div>
                        <h4 className="font-medium text-sm">Human Oversight</h4>
                        <p className="text-sm text-muted-foreground">{model.human_oversight}</p>
                      </div>
                      <div>
                        <h4 className="font-medium text-sm">Performance</h4>
                        <div className="flex gap-4 text-sm">
                          <span>Hallucination: {(model.performance_metrics?.hallucination_rate * 100).toFixed(1)}%</span>
                          <span>Latency P99: {model.performance_metrics?.latency_p99_ms}ms</span>
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="exports">
          <div className="grid gap-6 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Create Compliance Export</CardTitle>
                <CardDescription>Export all tenant data for GDPR Art. 20 portability or compliance audits</CardDescription>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleExportSubmit} className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium mb-1">Format</label>
                    <Select value={exportForm.format} onValueChange={(v) => setExportForm({ ...exportForm, format: v as "json" | "csv" | "pdf" })}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="json">JSON (structured)</SelectItem>
                        <SelectItem value="csv">CSV (tabular)</SelectItem>
                        <SelectItem value="pdf">PDF (report)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="grid gap-2 md:grid-cols-2">
                    <label className="flex items-center gap-2">
                      <input type="checkbox" checked={exportForm.include_audit_logs} onChange={(e) => setExportForm({ ...exportForm, include_audit_logs: e.target.checked })} />
                      <span>Include Audit Logs</span>
                    </label>
                    <label className="flex items-center gap-2">
                      <input type="checkbox" checked={exportForm.include_ai_decisions} onChange={(e) => setExportForm({ ...exportForm, include_ai_decisions: e.target.checked })} />
                      <span>Include AI Decisions</span>
                    </label>
                  </div>
                  <div className="grid gap-2 md:grid-cols-2">
                    <div>
                      <label className="block text-sm font-medium mb-1">Date From</label>
                      <Input type="date" value={exportForm.date_from} onChange={(e) => setExportForm({ ...exportForm, date_from: e.target.value })} />
                    </div>
                    <div>
                      <label className="block text-sm font-medium mb-1">Date To</label>
                      <Input type="date" value={exportForm.date_to} onChange={(e) => setExportForm({ ...exportForm, date_to: e.target.value })} />
                    </div>
                  </div>
                  <Button type="submit" disabled={exportLoading}>
                    {exportLoading ? "Generating..." : <><Download className="mr-2 h-4 w-4" /> Generate Export</>}
                  </Button>
                </form>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Export History</CardTitle>
                <CardDescription>Previous compliance exports available for download</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>ID</TableHead>
                        <TableHead>Format</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Created</TableHead>
                        <TableHead>Expires</TableHead>
                        <TableHead>Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.exports?.map((exp) => (
                        <TableRow key={exp.id}>
                          <TableCell className="font-mono text-xs">{exp.id.slice(0, 8)}...</TableCell>
                          <TableCell><Badge variant="secondary">{exp.format}</Badge></TableCell>
                          <TableCell>{getStatusBadge(exp.status)}</TableCell>
                          <TableCell>{format(new Date(exp.created_at), "MMM d, yyyy HH:mm")}</TableCell>
                          <TableCell>{exp.expires_at ? format(new Date(exp.expires_at), "MMM d, yyyy") : "N/A"}</TableCell>
                          <TableCell>
                            {exp.status === "completed" && exp.download_url && (
                              <a href={exp.download_url} target="_blank" rel="noopener noreferrer">
                                <Button variant="ghost" size="sm"><Download className="h-4 w-4" /></Button>
                              </a>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}