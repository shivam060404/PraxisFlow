import axios, { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from "axios";
import { getToken } from "@clerk/nextjs";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

class ApiClient {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: `${API_URL}/api/v1`,
      timeout: 60000,
      headers: {
        "Content-Type": "application/json",
      },
    });

    this.client.interceptors.request.use(
      async (config: InternalAxiosRequestConfig) => {
        try {
          const token = await getToken();
          if (token) {
            config.headers.Authorization = `Bearer ${token}`;
          }
        } catch (error) {
          // Token not available
        }
        return config;
      },
      (error) => Promise.reject(error)
    );

    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        if (error.response?.status === 401) {
          if (typeof window !== "undefined") {
            window.location.href = "/sign-in";
          }
        }
        return Promise.reject(error);
      }
    );
  }

  // ─── Health ───
  async healthCheck() {
    return this.client.get("/health");
  }

  async readinessCheck() {
    return this.client.get("/ready");
  }

  async livenessCheck() {
    return this.client.get("/live");
  }

  // ─── Meetings ───
  async getMeetings(params?: {
    page?: number;
    page_size?: number;
    status?: string;
  }) {
    return this.client.get("/meetings", { params });
  }

  async getMeeting(id: string) {
    return this.client.get(`/meetings/${id}`);
  }

  async createMeeting(data: FormData) {
    return this.client.post("/meetings/upload", data, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  }

  async updateMeeting(id: string, data: Partial<Meeting>) {
    return this.client.patch(`/meetings/${id}`, data);
  }

  async deleteMeeting(id: string) {
    return this.client.delete(`/meetings/${id}`);
  }

  async reprocessMeeting(id: string) {
    return this.client.post(`/meetings/${id}/process`);
  }

  async getMeetingStatus(id: string) {
    return this.client.get(`/meetings/${id}/status`);
  }

  // ─── Tasks ───
  async getTasks(params?: {
    page?: number;
    page_size?: number;
    meeting_id?: string;
    assignee_id?: string;
    status?: string;
    task_type?: string;
    priority?: string;
    search?: string;
  }) {
    return this.client.get("/tasks", { params });
  }

  async getTask(id: string) {
    return this.client.get(`/tasks/${id}`);
  }

  async updateTask(id: string, data: Partial<Task>) {
    return this.client.patch(`/tasks/${id}`, data);
  }

  async verifyTask(id: string, verification_status: string, reasoning?: string) {
    return this.client.post(`/tasks/${id}/verify`, {
      verification_status,
      reasoning,
    });
  }

  async assignTask(id: string, assignee_id: string) {
    return this.client.post(`/tasks/${id}/assign`, { assignee_id });
  }

  async dismissTask(id: string, reason?: string) {
    return this.client.post(`/tasks/${id}/dismiss`, { reason });
  }

  async bulkUpdateTasks(task_ids: string[], data: Partial<Task>) {
    return this.client.post("/tasks/bulk-update", { task_ids, ...data });
  }

  async getTaskAuditLog(id: string) {
    return this.client.get(`/tasks/${id}/audit-log`);
  }

  async getTaskSourceQuote(id: string, word_start: number, word_end: number) {
    return this.client.get(`/tasks/${id}/source-quote`, {
      params: { word_start, word_end },
    });
  }

  async syncTaskToIntegration(id: string, integration_id: string) {
    return this.client.post(`/tasks/${id}/sync`, { integration_id });
  }

  // ─── Users ───
  async getUsers() {
    return this.client.get("/users");
  }

  async getUser(id: string) {
    return this.client.get(`/users/${id}`);
  }

  async updateUser(id: string, data: Partial<User>) {
    return this.client.patch(`/users/${id}`, data);
  }

  // ─── Metrics & Analytics ───
  async getMetrics() {
    return this.client.get("/metrics");
  }

  async getDashboardMetrics() {
    return this.client.get("/metrics/dashboard");
  }

  async getTeamMetrics() {
    return this.client.get("/metrics/team");
  }

  async getExtractionAccuracy(params?: {
    start_date?: string;
    end_date?: string;
  }) {
    return this.client.get("/metrics/extraction-accuracy", { params });
  }

  async getPipelinePerformance(params?: {
    start_date?: string;
    end_date?: string;
  }) {
    return this.client.get("/metrics/pipeline-performance", { params });
  }

  async getCostAnalytics(params?: {
    start_date?: string;
    end_date?: string;
    group_by?: "model" | "pipeline_node" | "tenant";
  }) {
    return this.client.get("/metrics/cost", { params });
  }

  // ─── Transcripts ───
  async getTranscript(meetingId: string) {
    return this.client.get(`/transcripts/meeting/${meetingId}`);
  }

  async getTranscriptById(id: string) {
    return this.client.get(`/transcripts/${id}`);
  }

  async getUtterances(transcriptId: string, params?: {
    start_time_ms?: number;
    end_time_ms?: number;
    speaker_label?: string;
  }) {
    return this.client.get(`/transcripts/${transcriptId}/utterances`, { params });
  }

  async getTranscriptChunks(transcriptId: string, params?: {
    chunk_size?: number;
    overlap?: number;
  }) {
    return this.client.get(`/transcripts/${transcriptId}/chunks`, { params });
  }

  async getTranscriptSpan(transcriptId: string, word_start: number, word_end: number) {
    return this.client.get(`/transcripts/${transcriptId}/span`, {
      params: { word_start, word_end },
    });
  }

  async getTranscriptSpanByMeeting(meetingId: string, word_start: number, word_end: number) {
    return this.client.get(`/transcripts/meeting/${meetingId}/span`, {
      params: { word_start, word_end },
    });
  }

  async searchTranscript(transcriptId: string, query: string, limit?: number) {
    return this.client.get(`/transcripts/${transcriptId}/search`, {
      params: { q: query, limit },
    });
  }

  async getTranscriptStats(transcriptId: string) {
    return this.client.get(`/transcripts/${transcriptId}/stats`);
  }

  // ─── Integrations ───
  async getIntegrations() {
    return this.client.get("/integrations");
  }

  async getIntegration(id: string) {
    return this.client.get(`/integrations/${id}`);
  }

  async createIntegration(data: IntegrationCreate) {
    return this.client.post("/integrations", data);
  }

  async updateIntegration(id: string, data: Partial<IntegrationCreate>) {
    return this.client.patch(`/integrations/${id}`, data);
  }

  async deleteIntegration(id: string) {
    return this.client.delete(`/integrations/${id}`);
  }

  async testIntegration(id: string) {
    return this.client.post(`/integrations/${id}/test`);
  }

  async triggerIntegrationSync(id: string) {
    return this.client.post(`/integrations/${id}/sync`);
  }

  async getIntegrationHealth(id: string) {
    return this.client.get(`/integrations/${id}/health`);
  }

  // ─── WebSocket ───
  createWebSocket(tenantId: string): WebSocket {
    const wsUrl = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
    const token = typeof window !== "undefined" ? localStorage.getItem("clerk_token") : "";
    return new WebSocket(`${wsUrl}/api/v1/ws?token=${token}&tenant_id=${tenantId}`);
  }

  // ─── Admin (Tenant Management) ───
  async getTenant() {
    return this.client.get("/admin/tenant");
  }

  async updateTenant(data: TenantSettingsUpdate) {
    return this.client.patch("/admin/tenant", data);
  }

  async getTenantUsage() {
    return this.client.get("/admin/tenant/usage");
  }

  async getTenantUsers(params?: {
    page?: number;
    page_size?: number;
    role?: string;
    status?: string;
    search?: string;
  }) {
    return this.client.get("/admin/users", { params });
  }

  async inviteUser(data: UserInvite) {
    return this.client.post("/admin/users/invite", data);
  }

  async updateUser(id: string, data: Partial<User>) {
    return this.client.patch(`/admin/users/${id}`, data);
  }

  async bulkUserAction(data: BulkUserAction) {
    return this.client.post("/admin/users/bulk", data);
  }

  async getAdminIntegrations() {
    return this.client.get("/admin/integrations");
  }

  async createAdminIntegration(data: AdminIntegrationCreate) {
    return this.client.post("/admin/integrations", data);
  }

  async updateAdminIntegration(id: string, data: AdminIntegrationUpdate) {
    return this.client.patch(`/admin/integrations/${id}`, data);
  }

  async deleteAdminIntegration(id: string) {
    return this.client.delete(`/admin/integrations/${id}`);
  }

  async testAdminIntegration(id: string) {
    return this.client.post(`/admin/integrations/${id}/test`);
  }

  async triggerAdminSync(id: string) {
    return this.client.post(`/admin/integrations/${id}/sync`);
  }

  async getAdminAuditLogs(params?: {
    page?: number;
    page_size?: number;
    start_date?: string;
    end_date?: string;
    action?: string;
    user_id?: string;
  }) {
    return this.client.get("/admin/audit-logs", { params });
  }

  async getAdminComplianceStatus() {
    return this.client.get("/admin/compliance/status");
  }

  async getAdminSystemHealth() {
    return this.client.get("/admin/system/health");
  }

  async getAdminSystemMetrics() {
    return this.client.get("/admin/system/metrics");
  }

  // ─── Compliance ───
  async createDataSubjectRequest(data: DataSubjectRequestCreate) {
    return this.client.post("/compliance/data-subject-requests", data);
  }

  async getDataSubjectRequests(params?: {
    status?: string;
    limit?: number;
    offset?: number;
  }) {
    return this.client.get("/compliance/data-subject-requests", { params });
  }

  async getDataSubjectRequest(id: string) {
    return this.client.get(`/compliance/data-subject-requests/${id}`);
  }

  async processDataSubjectRequest(id: string) {
    return this.client.post(`/compliance/data-subject-requests/${id}/process`);
  }

  async exportTenantData(data: ComplianceExportRequest) {
    return this.client.post("/compliance/export", data);
  }

  async getExportStatus(exportId: string) {
    return this.client.get(`/compliance/exports/${exportId}`);
  }

  async eraseTenantData(confirmation: string) {
    return this.client.post("/compliance/erase-tenant", { confirmation });
  }

  async getAIAuditLogs(params?: {
    meeting_id?: string;
    task_id?: string;
    pipeline_node?: string;
    date_from?: string;
    date_to?: string;
    limit?: number;
    offset?: number;
  }) {
    return this.client.get("/compliance/ai-audit-logs", { params });
  }

  async getEUAIActStatus() {
    return this.client.get("/compliance/eu-ai-act");
  }

  async getGDPRStatus() {
    return this.client.get("/compliance/gdpr");
  }

  async getModelCards() {
    return this.client.get("/compliance/model-cards");
  }

  // ─── Webhooks ───
  async registerWebhook(data: WebhookRegistration) {
    return this.client.post("/webhooks/register", data);
  }

  async unregisterWebhook(provider: string) {
    return this.client.delete(`/webhooks/${provider}`);
  }

  async testWebhook(provider: string) {
    return this.client.get(`/webhooks/${provider}/test`);
  }

  async getWebhookLogs(provider: string, params?: {
    page?: number;
    page_size?: number;
  }) {
    return this.client.get(`/webhooks/${provider}/logs`, { params });
  }
}

// ─── Types ───
export interface Meeting {
  id: string;
  tenant_id: string;
  title: string;
  description?: string;
  scheduled_at: string;
  duration_minutes?: number;
  status: string;
  audio_url?: string;
  recording_source: string;
  calendar_event_id?: string;
  created_at: string;
  updated_at: string;
  transcript?: Transcript;
  attendees?: Attendee[];
  _count?: { tasks: number };
}

export interface Attendee {
  id: string;
  meeting_id: string;
  user_id?: string;
  email: string;
  display_name: string;
  speaker_label?: string;
  response_status: string;
  created_at: string;
  user?: User;
}

export interface User {
  id: string;
  tenant_id: string;
  email: string;
  full_name: string;
  avatar_url?: string;
  role: string;
  clerk_user_id?: string;
  created_at: string;
  updated_at: string;
  department?: string;
  team?: string;
  clearance_level?: string;
  is_active?: boolean;
  last_login?: string;
}

export interface Transcript {
  id: string;
  meeting_id: string;
  full_text: string;
  language: string;
  word_count: number;
  duration_ms: number;
  processed_at: string;
  redaction_applied: boolean;
  utterances?: Utterance[];
}

export interface Utterance {
  id: string;
  transcript_id: string;
  speaker_label: string;
  text: string;
  start_time_ms: number;
  end_time_ms: number;
  confidence?: number;
  word_start_idx?: number;
  word_end_idx?: number;
  has_redactions: boolean;
  redaction_map?: Record<string, unknown>;
}

export interface Task {
  id: string;
  tenant_id: string;
  meeting_id: string;
  title: string;
  description: string;
  task_type: string;
  status: string;
  priority?: string;
  assignee_hint?: string;
  assignee_id?: string;
  assignee_resolved_by?: string;
  deadline_hint?: string;
  deadline_date?: string;
  deadline_resolved_by?: string;
  transcript_word_start: number;
  transcript_word_end: number;
  source_quote: string;
  verification_status: string;
  verification_reasoning?: string;
  extraction_confidence: number;
  external_id?: string;
  external_url?: string;
  integration_id?: string;
  last_synced_at?: string;
  sync_status?: string;
  created_at: string;
  updated_at: string;
  created_by: string;
  assignee?: User;
  meeting?: Meeting;
  integration?: Integration;
  audit_logs?: TaskAuditLog[];
}

export interface TaskAuditLog {
  id: string;
  task_id: string;
  previous_status?: string;
  new_status: string;
  changed_by: string;
  reason?: string;
  metadata?: Record<string, unknown>;
  created_at: string;
}

export interface Integration {
  id: string;
  tenant_id: string;
  provider: string;
  display_name: string;
  status: string;
  config: Record<string, unknown>;
  webhook_secret?: string;
  created_at: string;
  updated_at: string;
}

export interface IntegrationCreate {
  provider: string;
  display_name: string;
  config: Record<string, unknown>;
  webhook_secret?: string;
}

// Admin Types
export interface TenantSettingsUpdate {
  name?: string;
  plan?: string;
  status?: string;
  settings?: Record<string, unknown>;
}

export interface UserInvite {
  email: string;
  full_name: string;
  role: "tenant_admin" | "team_lead" | "member" | "viewer" | "api_service";
  department?: string;
  team?: string;
}

export interface BulkUserAction {
  user_ids: string[];
  action: "activate" | "deactivate" | "delete" | "change_role";
  role?: "tenant_admin" | "team_lead" | "member" | "viewer" | "api_service";
}

export interface AdminIntegrationCreate {
  provider: string;
  display_name: string;
  config: Record<string, unknown>;
  webhook_secret?: string;
}

export interface AdminIntegrationUpdate {
  config: Record<string, unknown>;
  webhook_secret?: string;
}

// Compliance Types
export type DataSubjectRequestType =
  | "access"
  | "rectification"
  | "erasure"
  | "restriction"
  | "portability"
  | "objection";

export type DataSubjectRequestStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "rejected"
  | "extended";

export interface DataSubjectRequestCreate {
  request_type: DataSubjectRequestType;
  data_subject_email: string;
  reason?: string;
  specific_data_categories?: string[];
}

export interface DataSubjectRequestResponse {
  id: string;
  request_type: DataSubjectRequestType;
  data_subject_email: string;
  status: DataSubjectRequestStatus;
  reason?: string;
  created_at: string;
  updated_at: string;
  completed_at?: string;
  response_data?: Record<string, unknown>;
}

export interface ComplianceExportRequest {
  format: "json" | "csv" | "pdf";
  include_audit_logs: boolean;
  include_ai_decisions: boolean;
  date_from?: string;
  date_to?: string;
}

export interface AiAuditLogEntry {
  id: string;
  timestamp: string;
  decision_type: string;
  model: string;
  pipeline_node: string;
  input_hash: string;
  output_summary: string;
  verification_result?: Record<string, unknown>;
  guardrail_actions: string[];
  confidence_score?: number;
  latency_ms: number;
  cost_usd: number;
}

export interface EUAIActComplianceStatus {
  risk_management_system: boolean;
  data_governance: boolean;
  technical_documentation: boolean;
  record_keeping: boolean;
  transparency: boolean;
  human_oversight: boolean;
  accuracy_robustness: boolean;
  cybersecurity: boolean;
  overall_compliant: boolean;
  last_assessment: string;
  next_assessment: string;
}

export interface GDPRComplianceStatus {
  lawful_basis_documented: boolean;
  dpia_completed: boolean;
  dpia_last_reviewed?: string;
  data_processing_agreements: boolean;
  dpa_last_reviewed?: string;
  data_subject_rights_process: boolean;
  breach_notification_process: boolean;
  data_retention_policy: boolean;
  cross_border_transfers: boolean;
  sccs_in_place: boolean;
  overall_compliant: boolean;
}

export interface WebhookRegistration {
  provider: string;
  url: string;
  events: string[];
  secret?: string;
}

export const api = new ApiClient();