-- ============================================================================
-- PraxisFlow — PostgreSQL initialization (Prisma-compatible)
-- ============================================================================
-- Extensions ONLY.
--
-- Ownership of schema objects:
--   Tables/enums ......... Prisma  (cd backend && prisma db push)
--   Row-Level Security ... infrastructure/docker/rls-setup.sql
--                          (apply AFTER `prisma db push`)
--   Dev seed data ........ backend/scripts/seed_dev.py
--
-- The previous version of this file hand-created lowercase tables that
-- conflicted with Prisma's PascalCase models. That split-brain schema is
-- gone: one source of truth.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";
