import axios, { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from "axios";
import { getToken } from "@clerk/nextjs";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

class ApiClient {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: `${API_URL}/api/v1`,
      timeout: 30000,
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
          // Handle unauthorized - redirect to sign in
          if (typeof window !== "undefined") {
            window.location.href = "/sign-in";
          }
        }
        return Promise.reject(error);
      }
    );
  }

  // Meetings
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

  // Tasks
  async getTasks(params?: {
    page?: number;
    page_size?: number;
    meeting_id?: string;
    assignee_id?: string;
    status?: string;
    task_type?: string;
    priority?: string;
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

  async getUsers() {
    return this.client.get("/users");
  }

  async getMetrics() {
    return this.client.get("/metrics");
  }

  // Transcripts
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

  // Integrations
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

  // Health
  async healthCheck() {
    return this.client.get("/health");
  }
}

// Types
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

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export const api = new ApiClient();