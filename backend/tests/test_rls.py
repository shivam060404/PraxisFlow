"""
Row-Level Security integration tests.

These tests verify the DATABASE-level tenant isolation defined in
infrastructure/docker/rls-setup.sql. They require:
  - a live PostgreSQL with the Prisma schema applied (prisma db push)
  - rls-setup.sql applied
  - TEST_RLS_DATABASE_URL pointing at a connection string for the
    restricted `praxisflow_app` role

Skipped automatically when TEST_RLS_DATABASE_URL is not set, so unit runs
stay hermetic.

    TEST_RLS_DATABASE_URL=postgres://praxisflow_app:pw@localhost:5432/ami \
        pytest tests/test_rls.py -v
"""

import os
import uuid

import pytest

pytest.importorskip("psycopg")

TEST_RLS_URL = os.environ.get("TEST_RLS_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_RLS_URL,
    reason="TEST_RLS_DATABASE_URL not configured; RLS tests need a live DB",
)


@pytest.fixture()
def db():
    import psycopg

    conn = psycopg.connect(TEST_RLS_URL, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


def _set_tenant(conn, tenant_id: str):
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.current_tenant', %s, false)", (tenant_id,))


def _seed_tenant_with_meeting(conn) -> tuple[str, str]:
    """Create two tenants; a meeting in tenant A. Returns (tenant_a, tenant_b)."""

    def mk_tenant(name):
        tid = str(uuid.uuid4())
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "Tenant" ("id", "name", "slug", "plan", "status") '
                "VALUES (%s, %s, %s, 'starter', 'active')",
                (tid, name, f"rlstest-{tid[:8]}"),
            )
        return tid

    tenant_a = mk_tenant("rls-a")
    tenant_b = mk_tenant("rls-b")

    mid = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Meeting" ("id", "tenantId", "title", "scheduledAt", '
            '"recordingSource", "status") '
            "VALUES (%s, %s, %s, NOW(), 'upload', 'COMPLETED')",
            (mid, tenant_a, "RLS test meeting"),
        )
    return tenant_a, tenant_b


class TestRowLevelSecurity:
    def test_cross_tenant_select_returns_nothing(self, db):
        tenant_a, tenant_b = _seed_tenant_with_meeting(db)

        # As tenant B, the meeting owned by tenant A must be invisible
        _set_tenant(db, tenant_b)
        with db.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM "Meeting" WHERE "title" = %s', ("RLS test meeting",))
            count = cur.fetchone()[0]
        assert count == 0, "RLS failed: another tenant's meeting is visible"

    def test_same_tenant_select_works(self, db):
        tenant_a, _ = _seed_tenant_with_meeting(db)

        _set_tenant(db, tenant_a)
        with db.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) FROM "Meeting" WHERE "title" = %s AND "tenantId" = %s',
                ("RLS test meeting", tenant_a),
            )
            count = cur.fetchone()[0]
        assert count == 1

    def test_unset_context_denies_everything(self, db):
        tenant_a, _ = _seed_tenant_with_meeting(db)

        # No GUC set on this fresh connection → policies deny all rows
        with db.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM "Meeting" WHERE "tenantId" = %s', (tenant_a,))
            count = cur.fetchone()[0]
        assert count == 0, "RLS failed: rows visible without tenant context"

    def test_cross_tenant_insert_blocked(self, db):
        _, tenant_b = _seed_tenant_with_meeting(db)

        _set_tenant(db, tenant_b)
        with pytest.raises(Exception):
            with db.cursor() as cur:
                # Attempt to write a row claiming tenant A ownership
                cur.execute(
                    'INSERT INTO "Meeting" ("id", "tenantId", "title", "scheduledAt", '
                    '"recordingSource", "status") VALUES (%s, %s, %s, NOW(), %s, %s)',
                    (str(uuid.uuid4()), "not-my-tenant", "evil", "upload", "UPLOADED"),
                )

    def test_child_table_scoped_through_parent(self, db):
        tenant_a, tenant_b = _seed_tenant_with_meeting(db)

        trid = str(uuid.uuid4())
        with db.cursor() as cur:
            # Find the meeting created in this test run for tenant A
            cur.execute(
                'SELECT "id" FROM "Meeting" WHERE "tenantId" = %s AND "title" = %s LIMIT 1',
                (tenant_a, "RLS test meeting"),
            )
            mid = cur.fetchone()[0]
            cur.execute(
                'INSERT INTO "Transcript" ("id", "meetingId", "fullText", "language") '
                "VALUES (%s, %s, %s, %s)",
                (trid, mid, "hello world", "en"),
            )

        # Tenant B must not see the transcript scoped through the meeting
        _set_tenant(db, tenant_b)
        with db.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM "Transcript" WHERE "id" = %s', (trid,))
            assert cur.fetchone()[0] == 0

        # Owner tenant can see it
        _set_tenant(db, tenant_a)
        with db.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM "Transcript" WHERE "id" = %s', (trid,))
            assert cur.fetchone()[0] == 1
