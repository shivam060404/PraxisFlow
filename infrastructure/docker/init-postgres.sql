-- PostgreSQL initialization script for AMI
-- Enables extensions and sets up Row Level Security

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Create custom types
CREATE TYPE meeting_status AS ENUM (
    'UPLOADED', 'PROCESSING', 'TRANSCRIBED', 'EXTRACTED', 'COMPLETED', 'ERROR'
);

CREATE TYPE task_status AS ENUM (
    'EXTRACTED', 'PENDING_REVIEW', 'VERIFIED', 'ASSIGNED', 'SYNCED', 'COMPLETED', 'DISMISSED'
);

CREATE TYPE task_type AS ENUM (
    'ACTION_ITEM', 'DECISION', 'FOLLOW_UP', 'BLOCKER'
);

CREATE TYPE verification_status AS ENUM (
    'PENDING', 'VERIFIED', 'NEEDS_REVIEW', 'FAILED'
);

CREATE TYPE sync_status AS ENUM (
    'PENDING', 'SYNCED', 'SYNC_FAILED', 'CONFLICT'
);

CREATE TYPE integration_provider AS ENUM (
    'jira', 'asana', 'linear', 'slack', 'teams'
);

-- Create function to set current tenant for RLS
CREATE OR REPLACE FUNCTION set_current_tenant(tenant_id UUID)
RETURNS VOID AS $$
BEGIN
    PERFORM set_config('app.current_tenant', tenant_id::text, false);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Create function to get current tenant
CREATE OR REPLACE FUNCTION current_tenant_id()
RETURNS UUID AS $$
BEGIN
    RETURN current_setting('app.current_tenant')::UUID;
EXCEPTION
    WHEN OTHERS THEN
        RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

-- Tenants table
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    plan VARCHAR(50) DEFAULT 'starter',
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    avatar_url TEXT,
    role VARCHAR(50) DEFAULT 'member',
    clerk_user_id VARCHAR(255) UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, email)
);

-- Enable RLS on users
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_users ON users
    USING (tenant_id = current_tenant_id());

-- Meetings table
CREATE TABLE meetings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    scheduled_at TIMESTAMPTZ NOT NULL,
    duration_minutes INTEGER,
    status meeting_status DEFAULT 'UPLOADED',
    audio_url TEXT,
    recording_source VARCHAR(50) DEFAULT 'upload',
    calendar_event_id VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Enable RLS on meetings
ALTER TABLE meetings ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_meetings ON meetings
    USING (tenant_id = current_tenant_id());

CREATE INDEX idx_meetings_tenant_status ON meetings(tenant_id, status);
CREATE INDEX idx_meetings_tenant_scheduled ON meetings(tenant_id, scheduled_at);

-- Attendees table
CREATE TABLE attendees (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    email VARCHAR(255) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    speaker_label VARCHAR(50),
    response_status VARCHAR(50) DEFAULT 'accepted',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(meeting_id, email)
);

ALTER TABLE attendees ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_attendees ON attendees
    USING (meeting_id IN (SELECT id FROM meetings WHERE tenant_id = current_tenant_id()));

CREATE INDEX idx_attendees_meeting ON attendees(meeting_id);

-- Transcripts table
CREATE TABLE transcripts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    meeting_id UUID NOT NULL UNIQUE REFERENCES meetings(id) ON DELETE CASCADE,
    full_text TEXT NOT NULL,
    language VARCHAR(10) DEFAULT 'en',
    word_count INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    processed_at TIMESTAMPTZ DEFAULT NOW(),
    redaction_applied BOOLEAN DEFAULT FALSE
);

ALTER TABLE transcripts ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_transcripts ON transcripts
    USING (meeting_id IN (SELECT id FROM meetings WHERE tenant_id = current_tenant_id()));

CREATE INDEX idx_transcripts_meeting ON transcripts(meeting_id);

-- Utterances table (individual speech segments)
CREATE TABLE utterances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transcript_id UUID NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    speaker_label VARCHAR(50) NOT NULL,
    text TEXT NOT NULL,
    start_time_ms INTEGER NOT NULL,
    end_time_ms INTEGER NOT NULL,
    confidence DOUBLE PRECISION,
    word_start_idx INTEGER,
    word_end_idx INTEGER,
    has_redactions BOOLEAN DEFAULT FALSE,
    redaction_map JSONB
);

ALTER TABLE utterances ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_utterances ON utterances
    USING (transcript_id IN (SELECT id FROM transcripts WHERE meeting_id IN (SELECT id FROM meetings WHERE tenant_id = current_tenant_id())));

CREATE INDEX idx_utterances_transcript_word_start ON utterances(transcript_id, word_start_idx);
CREATE INDEX idx_utterances_transcript_time ON utterances(transcript_id, start_time_ms);

-- Tasks table (extracted action items, decisions, etc.)
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    description TEXT NOT NULL,
    task_type task_type NOT NULL,
    status task_status DEFAULT 'EXTRACTED',
    priority VARCHAR(20),
    
    -- Assignee resolution
    assignee_hint TEXT,
    assignee_id UUID REFERENCES users(id) ON DELETE SET NULL,
    assignee_resolved_by VARCHAR(50),
    
    -- Deadline resolution
    deadline_hint TEXT,
    deadline_date TIMESTAMPTZ,
    deadline_resolved_by VARCHAR(50),
    
    -- Transcript provenance
    transcript_word_start INTEGER NOT NULL,
    transcript_word_end INTEGER NOT NULL,
    source_quote TEXT NOT NULL,
    
    -- Verification
    verification_status verification_status DEFAULT 'PENDING',
    verification_reasoning TEXT,
    extraction_confidence DOUBLE PRECISION,
    
    -- Integration sync
    external_id VARCHAR(255),
    external_url TEXT,
    integration_id UUID,
    last_synced_at TIMESTAMPTZ,
    sync_status sync_status,
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(50) DEFAULT 'ai_agent'
);

ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_tasks ON tasks
    USING (tenant_id = current_tenant_id());

CREATE INDEX idx_tasks_tenant_status ON tasks(tenant_id, status);
CREATE INDEX idx_tasks_tenant_assignee ON tasks(tenant_id, assignee_id);
CREATE INDEX idx_tasks_meeting_type ON tasks(meeting_id, task_type);
CREATE INDEX idx_tasks_assignee_status ON tasks(assignee_id, status);
CREATE INDEX idx_tasks_external ON tasks(external_id, integration_id);

-- Task audit log (event sourcing for state machine)
CREATE TABLE task_audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    previous_status task_status,
    new_status task_status NOT NULL,
    changed_by VARCHAR(255) NOT NULL,
    reason TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE task_audit_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_task_audit ON task_audit_logs
    USING (task_id IN (SELECT id FROM tasks WHERE tenant_id = current_tenant_id()));

CREATE INDEX idx_task_audit_task_created ON task_audit_logs(task_id, created_at);

-- Integrations table
CREATE TABLE integrations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider integration_provider NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'ACTIVE',
    config JSONB NOT NULL DEFAULT '{}',
    webhook_secret VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, provider)
);

ALTER TABLE integrations ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_integrations ON integrations
    USING (tenant_id = current_tenant_id());

CREATE INDEX idx_integrations_tenant ON integrations(tenant_id);

-- AI Audit logs (for explainable AI)
CREATE TABLE ai_audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    meeting_id UUID REFERENCES meetings(id) ON DELETE SET NULL,
    decision_type VARCHAR(100) NOT NULL,
    model VARCHAR(100) NOT NULL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    raw_input_hash VARCHAR(64),
    raw_output TEXT,
    structured_output JSONB,
    verification_result JSONB,
    latency_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE ai_audit_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_ai_audit ON ai_audit_logs
    USING (tenant_id = current_tenant_id());

CREATE INDEX idx_ai_audit_tenant_created ON ai_audit_logs(tenant_id, created_at);
CREATE INDEX idx_ai_audit_task ON ai_audit_logs(task_id);

-- Meeting flags (for manual review)
CREATE TABLE meeting_flags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    flag_type VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    resolved BOOLEAN DEFAULT FALSE,
    resolved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE meeting_flags ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_meeting_flags ON meeting_flags
    USING (meeting_id IN (SELECT id FROM meetings WHERE tenant_id = current_tenant_id()));

-- Insert a default tenant for development
INSERT INTO tenants (id, name, slug, plan, status) 
VALUES ('00000000-0000-0000-0000-000000000001', 'Development Tenant', 'dev', 'enterprise', 'active')
ON CONFLICT (slug) DO NOTHING;