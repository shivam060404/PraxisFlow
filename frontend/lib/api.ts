import axios, { AxiosInstance, AxiosError, AxiosRequestConfig, InternalAxiosRequestConfig } from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const DEV_AUTH_ENABLED = process.env.NEXT_PUBLIC_DEV_AUTH !== "false";
const DEV_EMAIL = process.env.NEXT_PUBLIC_DEV_EMAIL || "admin@dev.local";
const TOKEN_KEY = "auth_token";

/**
 * Development auth bootstrap: mint a local JWT from the backend's
 * development-only /auth/dev-token endpoint and cache it.
 *
 * In production (Clerk mode) this endpoint 404s and the Clerk session
 * supplies the bearer token instead.
 */
async function ensureDevAuthToken(): Promise<string | null> {
  if (!DEV_AUTH_ENABLED || typeof window === "undefined") return null;
  const existing = localStorage.getItem(TOKEN_KEY);
  if (existing) return existing;

  try {
    const resp = await fetch(`${API_URL}/api/v1/auth/dev-token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: DEV_EMAIL }),
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    localStorage.setItem(TOKEN_KEY, data.access_token);
    return data.access_token;
  } catch {
    return null;
  }
}

/**
 * The response interceptor unwraps payloads (`response.data`), so callers
 * receive plain data instead of AxiosResponse envelopes. This type reflects
 * that runtime contract.
 */
interface UnwrappedClient {
  get: (url: string, config?: AxiosRequestConfig) => Promise<any>;
  post: (url: string, data?: unknown, config?: AxiosRequestConfig) => Promise<any>;
  patch: (url: string, data?: unknown, config?: AxiosRequestConfig) => Promise<any>;
  put: (url: string, data?: unknown, config?: AxiosRequestConfig) => Promise<any>;
  delete: (url: string, config?: AxiosRequestConfig) => Promise<any>;
}

class ApiClient {
  private client: AxiosInstance;
  private http: UnwrappedClient;

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
          // Resolve a bearer token: Clerk session when configured, else the
          // cached/minted local dev token so the dashboard works out of the box.
          const w = window as unknown as {
            Clerk?: { session?: { getToken?: () => Promise<string | null> } };
          };
          let token: string | null | undefined =
            await w.Clerk?.session?.getToken?.();
          if (!token && typeof localStorage !== "undefined") {
            token = localStorage.getItem(TOKEN_KEY);
          }
          if (!token && DEV_AUTH_ENABLED) {
            token = await ensureDevAuthToken();
          }
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
      (response) => {
        // Unwrap payloads so callers work with data directly
        return response.data as unknown as typeof response;
      },
      async (error: AxiosError) => {
        if (error.response?.status === 401 && typeof window !== "undefined") {
          const usedDevToken =
            DEV_AUTH_ENABLED && localStorage.getItem(TOKEN_KEY) !== null;
          if (usedDevToken) {
            // Stale dev token: clear it so the next request re-mints
            localStorage.removeItem(TOKEN_KEY);
            return Promise.reject(error);
          }
          if (!DEV_AUTH_ENABLED) {
            window.location.href = "/sign-in";
          }
        }
        return Promise.reject(error);
      }
    );

    this.http = this.client as unknown as UnwrappedClient;
  }

  // ─── Health ───
  async healthCheck() {
    return this.http.get("/health");
  }

  async readinessCheck() {
    return this.http.get("/ready");
  }

  async livenessCheck() {
    return this.http.get("/live");
  }

  // ─── Meetings ───
  async getMeetings(params?: {
    page?: number;
    page_size?: number;
    status?: string;
  }) {
    return this.http.get("/meetings", { params });
  }

  async getMeeting(id: string) {
    return this.http.get(`/meetings/${id}`);
  }

  async createMeeting(data: FormData) {
    return this.http.post("/meetings/upload", data, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  }

  async updateMeeting(id: string, data: Partial<Meeting>) {
    return this.http.patch(`/meetings/${id}`, data);
  }

  async deleteMeeting(id: string) {
    return this.http.delete(`/meetings/${id}`);
  }

  async reprocessMeeting(id: string) {
    return this.http.post(`/meetings/${id}/process`);
  }

  async getMeetingStatus(id: string) {
    return this.http.get(`/meetings/${id}/status`);
  }

  // ─── Tasks ───
  async getTasks(params?: {
    page?: number;
    page_size?: number;
    meeting_id?: string | string[];
    assignee_id?: string | string[];
    status?: string | string[];
    task_type?: string | string[];
    priority?: string | string[];
    search?: string;
    date_from?: string;
    date_to?: string;
  }) {
    return this.http.get("/tasks", { params });
  }

  async getTask(id: string) {
    return this.http.get(`/tasks/${id}`);
  }

  async updateTask(id: string, data: Partial<Task>) {
    return this.http.patch(`/tasks/${id}`, data);
  }

  async verifyTask(id: string, verification_status: string, reasoning?: string) {
    return this.http.post(`/tasks/${id}/verify`, {
      verification_status,
      reasoning,
    });
  }

  async assignTask(id: string, assignee_id: string) {
    return this.http.post(`/tasks/${id}/assign`, { assignee_id });
  }

  async dismissTask(id: string, reason?: string) {
    return this.http.post(`/tasks/${id}/dismiss`, { reason });
  }

  async bulkUpdateTasks(task_ids: string[], data: Partial<Task>) {
    return this.http.post("/tasks/bulk-update", { task_ids, ...data });
  }

  async getTaskAuditLog(id: string) {
    return this.http.get(`/tasks/${id}/audit-log`);
  }

  async getTaskSourceQuote(id: string, word_start: number, word_end: number) {
    return this.http.get(`/tasks/${id}/source-quote`, {
      params: { word_start, word_end },
    });
  }

  async syncTaskToIntegration(id: string, integration_id: string) {
    return this.http.post(`/tasks/${id}/sync`, { integration_id });
  }

  // ─── Users ───
  async getUsers(params?: { search?: string; role?: string; status?: string; page?: number; page_size?: number }) {
    return this.http.get("/users", { params });
  }

  async getCurrentUserProfile() {
    return this.http.get("/users/me/profile");
  }

  async createUser(data: {
    email: string;
    full_name: string;
    role?: string;
  }) {
    return this.http.post("/users", data);
  }

  async getUser(id: string) {
    return this.http.get(`/users/${id}`);
  }

  async updateUser(id: string, data: Partial<User>) {
    return this.http.patch(`/users/${id}`, data);
  }

  // ─── Metrics & Analytics ───
  async getMetrics() {
    return this.http.get("/metrics");
  }

  async getDashboardMetrics() {
    return this.http.get("/metrics/dashboard");
  }

  async getTeamMetrics() {
    return this.http.get("/metrics/team");
  }

  async getExtractionAccuracy(params?: {
    start_date?: string;
    end_date?: string;
  }) {
    return this.http.get("/metrics/extraction-accuracy", { params });
  }

  async getPipelinePerformance(params?: {
    start_date?: string;
    end_date?: string;
  }) {
    return this.http.get("/metrics/pipeline-performance", { params });
  }

  async getCostAnalytics(params?: {
    start_date?: string;
    end_date?: string;
    group_by?: "model" | "pipeline_node" | "tenant";
  }) {
    return this.http.get("/metrics/cost", { params });
  }

  // ─── Transcripts ───
  async getTranscript(meetingId: string) {
    return this.http.get(`/transcripts/meeting/${meetingId}`);
  }

  async getTranscriptById(id: string) {
    return this.http.get(`/transcripts/${id}`);
  }

  async getUtterances(transcriptId: string, params?: {
    start_time_ms?: number;
    end_time_ms?: number;
    speaker_label?: string;
  }) {
    return this.http.get(`/transcripts/${transcriptId}/utterances`, { params });
  }

  async getTranscriptChunks(transcriptId: string, params?: {
    chunk_size?: number;
    overlap?: number;
  }) {
    return this.http.get(`/transcripts/${transcriptId}/chunks`, { params });
  }

  async getTranscriptSpan(transcriptId: string, word_start: number, word_end: number) {
    return this.http.get(`/transcripts/${transcriptId}/span`, {
      params: { word_start, word_end },
    });
  }

  async getTranscriptSpanByMeeting(meetingId: string, word_start: number, word_end: number) {
    return this.http.get(`/transcripts/meeting/${meetingId}/span`, {
      params: { word_start, word_end },
    });
  }

  async searchTranscript(transcriptId: string, query: string, limit?: number) {
    return this.http.get(`/transcripts/${transcriptId}/search`, {
      params: { q: query, limit },
    });
  }

  async getTranscriptStats(transcriptId: string) {
    return this.http.get(`/transcripts/${transcriptId}/stats`);
  }

  // ─── Integrations ───
  async getIntegrations() {
    return this.http.get("/integrations");
  }

  async getIntegration(id: string) {
    return this.http.get(`/integrations/${id}`);
  }

  async createIntegration(data: IntegrationCreate) {
    return this.http.post("/integrations", data);
  }

  async updateIntegration(id: string, data: Partial<IntegrationCreate>) {
    return this.http.patch(`/integrations/${id}`, data);
  }

  async deleteIntegration(id: string) {
    return this.http.delete(`/integrations/${id}`);
  }

  async testIntegration(id: string) {
    return this.http.post(`/integrations/${id}/test`);
  }

  async triggerIntegrationSync(id: string) {
    return this.http.post(`/integrations/${id}/sync`);
  }

  async getIntegrationHealth(id: string) {
    return this.http.get(`/integrations/${id}/health`);
  }

  // ─── WebSocket ───
  createWebSocket(tenantId: string): WebSocket {
    const wsUrl = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
    const token =
      typeof window !== "undefined"
        ? localStorage.getItem(TOKEN_KEY) ?? ""
        : "";
    return new WebSocket(`${wsUrl}/api/v1/ws?token=${encodeURIComponent(token)}&tenant_id=${tenantId}`);
  }

  // ─── Admin (Tenant Management) ───
  async getTenant() {
    return this.http.get("/admin/tenant");
  }

  async updateTenant(data: TenantSettingsUpdate) {
    return this.http.patch("/admin/tenant", data);
  }

  async getTenantUsage() {
    return this.http.get("/admin/tenant/usage");
  }

  async getTenantUsers(params?: {
    page?: number;
    page_size?: number;
    role?: string;
    status?: string;
    search?: string;
  }) {
    return this.http.get("/admin/users", { params });
  }

  async inviteUser(data: UserInvite) {
    return this.http.post("/admin/users/invite", data);
  }

  async updateAdminUser(id: string, data: Partial<User>) {
    return this.http.patch(`/admin/users/${id}`, data);
  }

  async bulkUserAction(data: BulkUserAction) {
    return this.http.post("/admin/users/bulk", data);
  }

  async getAdminIntegrations() {
    return this.http.get("/admin/integrations");
  }

  async createAdminIntegration(data: AdminIntegrationCreate) {
    return this.http.post("/admin/integrations", data);
  }

  async updateAdminIntegration(id: string, data: AdminIntegrationUpdate) {
    return this.http.patch(`/admin/integrations/${id}`, data);
  }

  async deleteAdminIntegration(id: string) {
    return this.http.delete(`/admin/integrations/${id}`);
  }

  async testAdminIntegration(id: string) {
    return this.http.post(`/admin/integrations/${id}/test`);
  }

  async triggerAdminSync(id: string) {
    return this.http.post(`/admin/integrations/${id}/sync`);
  }

  async getAdminAuditLogs(params?: {
    page?: number;
    page_size?: number;
    start_date?: string;
    end_date?: string;
    action?: string;
    user_id?: string;
  }) {
    return this.http.get("/admin/audit-logs", { params });
  }

  async getAdminComplianceStatus() {
    return this.http.get("/admin/compliance/status");
  }

  async getAdminSystemHealth() {
    return this.http.get("/admin/system/health");
  }

  async getAdminSystemMetrics() {
    return this.http.get("/admin/system/metrics");
  }

  // ─── Compliance ───
  async createDataSubjectRequest(data: DataSubjectRequestCreate) {
    return this.http.post("/compliance/data-subject-requests", data);
  }

  async getDataSubjectRequests(params?: {
    status?: string;
    limit?: number;
    offset?: number;
  }) {
    return this.http.get("/compliance/data-subject-requests", { params });
  }

  async getDataSubjectRequest(id: string) {
    return this.http.get(`/compliance/data-subject-requests/${id}`);
  }

  async processDataSubjectRequest(id: string) {
    return this.http.post(`/compliance/data-subject-requests/${id}/process`);
  }

  async exportTenantData(data: ComplianceExportRequest) {
    return this.http.post("/compliance/export", data);
  }

  async getExportStatus(exportId: string) {
    return this.http.get(`/compliance/exports/${exportId}`);
  }

  async eraseTenantData(confirmation: string) {
    return this.http.post("/compliance/erase-tenant", { confirmation });
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
    return this.http.get("/compliance/ai-audit-logs", { params });
  }

  async getEUAIActStatus() {
    return this.http.get("/compliance/eu-ai-act");
  }

  async getGDPRStatus() {
    return this.http.get("/compliance/gdpr");
  }

  async getModelCards() {
    return this.http.get("/compliance/model-cards");
  }

  // ─── Webhooks ───
  async registerWebhook(data: WebhookRegistration) {
    return this.http.post("/webhooks/register", data);
  }

  async unregisterWebhook(provider: string) {
    return this.http.delete(`/webhooks/${provider}`);
  }

  async testWebhook(provider: string) {
    return this.http.get(`/webhooks/${provider}/test`);
  }

  async getWebhookLogs(provider: string, params?: {
    page?: number;
    page_size?: number;
  }) {
    return this.http.get(`/webhooks/${provider}/logs`, { params });
  }
}

// ─── Types ───
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page?: number;
  page_size?: number;
}

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

export type TaskStatus =
  | "EXTRACTED"
  | "PENDING_REVIEW"
  | "VERIFIED"
  | "ASSIGNED"
  | "SYNCED"
  | "SYNC_FAILED"
  | "CONFLICT"
  | "COMPLETED"
  | "DISMISSED";

export type Priority = "HIGH" | "MEDIUM" | "LOW";

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
  config: Record<string, any>;
  webhook_secret?: string;
  created_at: string;
  updated_at: string;
}

export interface IntegrationCreate {
  provider: string;
  display_name: string;
  config: Record<string, any>;
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
  config: Record<string, any>;
  webhook_secret?: string;
}

export interface AdminIntegrationUpdate {
  config: Record<string, any>;
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