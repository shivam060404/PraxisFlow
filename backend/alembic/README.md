# Database migrations

The current backend uses Prisma migrations from `backend/prisma` as its
authoritative schema and migration system. This directory is reserved for a
future Alembic migration layer; it is intentionally not wired into runtime
startup so introducing it does not create two competing sources of truth.
