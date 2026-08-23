"""
Row-Level Security integration tests.

Proves the DATABASE-level tenant isolation defined in
infrastructure/docker/rls-setup.sql using two connections:

  - ADMIN: schema owner / superuser — seeds fixture data (bypasses RLS*)
  - RESTRICTED: `praxisflow_app` — every assertion runs through this;
    policies apply because the role does not own tables

Setup requirements (see README → Production Deployment):
  - Prisma schema applied (`prisma db push`)
  - rls-setup.sql applied
  - TEST_RLS_DATABASE_URL      → postgres://praxisflow_app:pw@host/db
  - TEST_RLS_ADMIN_URL         → privileged URL for seeding (optional;
                                 falls back to TEST_RLS_DATABASE_URL's DB
                                 via local defaults)

Skipped automatically when TEST_RLS_DATABASE_URL is not set.

    TEST_RLS_DATABASE_URL=postgres://praxisflow_app:pw@localhost:5432/ami \
    TEST_RLS_ADMIN_URL=postgres://ami:pw@localhost:5432/ami \
        pytest tests/test_rls.py -v
"""

import os
import uuid

import pytest

pytest.importorskip("psycopg")

RESTRICTED_URL = os.environ.get("TEST_RLS_DATABASE_URL")
ADMIN_URL = os.environ.get("TEST_RLS_ADMIN_URL")

pytestmark = pytest.mark.skipif(
    not RESTRICTED_URL,
    reason="TEST_RLS_DATABASE_URL not configured; RLS tests need a live DB",
)


@pytest.fixture()
def admin_db():
    import psycopg

    url = ADMIN_URL or RESTRICTED_URL
    conn = psycopg.connect(url, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def db():
    """Restricted-role connection: RLS applies."""
    import psycopg

    conn = psycopg.connect(RESTRICTED_URL, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def seeded(admin_db):
    """Two tenants + a meeting in tenant A. Returns (tenant_a, tenant_b)."""

    def mk_tenant(name):
        tid = str(uuid.uuid4())
        with admin_db.cursor() as cur:
            cur.execute(
                'INSERT INTO "Tenant" ("id", "name", "slug", "plan", "status", '
                '"createdAt", "updatedAt") '
                "VALUES (%s, %s, %s, 'starter', 'active', NOW(), NOW())",
                (tid, name, f"rlstest-{tid[:8]}"),
            )
        return tid

    tenant_a = mk_tenant("rls-a")
    tenant_b = mk_tenant("rls-b")

    mid = str(uuid.uuid4())
    with admin_db.cursor() as cur:
        cur.execute(
            'INSERT INTO "Meeting" ("id", "tenantId", "title", "scheduledAt", '
            '"recordingSource", "status", "createdAt", "updatedAt") '
            "VALUES (%s, %s, %s, NOW(), 'upload', 'COMPLETED', NOW(), NOW())",
            (mid, tenant_a, "RLS test meeting"),
        )
    yield tenant_a, tenant_b, mid

    # Cleanup so repeated runs stay clean
    with admin_db.cursor() as cur:
        cur.execute('DELETE FROM "Meeting" WHERE "id" = %s', (mid,))
        cur.execute('DELETE FROM "Tenant" WHERE "id" IN (%s, %s)', (tenant_a, tenant_b))


def _set_tenant(conn, tenant_id: str):
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.current_tenant', %s, false)", (tenant_id,))


class TestRowLevelSecurity:
    def test_cross_tenant_select_returns_nothing(self, db, seeded):
        tenant_a, tenant_b, _ = seeded

        _set_tenant(db, tenant_b)
        with db.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) FROM "Meeting" WHERE "title" = %s',
                ("RLS test meeting",),
            )
            count = cur.fetchone()[0]
        assert count == 0, "RLS failed: another tenant's meeting is visible"

    def test_same_tenant_select_works(self, admin_db, db, seeded):
        tenant_a, _, mid = seeded

        _set_tenant(db, tenant_a)
        with db.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM "Meeting" WHERE "id" = %s', (mid,))
            count = cur.fetchone()[0]
        assert count == 1

    def test_unset_context_denies_everything(self, db, seeded):
        tenant_a, _, _ = seeded

        # Fresh restricted connection, no GUC set → deny all
        with db.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) FROM "Meeting" WHERE "tenantId" = %s',
                (tenant_a,),
            )
            count = cur.fetchone()[0]
        assert count == 0, "RLS failed: rows visible without tenant context"

    def test_cross_tenant_insert_blocked(self, db, seeded):
        _, tenant_b, _ = seeded

        _set_tenant(db, tenant_b)
        with pytest.raises(Exception):
            with db.cursor() as cur:
                cur.execute(
                    'INSERT INTO "Meeting" ("id", "tenantId", "title", "scheduledAt", '
                    '"recordingSource", "status", "createdAt", "updatedAt") '
                    "VALUES (%s, %s, %s, NOW(), %s, %s, NOW(), NOW())",
                    (str(uuid.uuid4()), "not-my-tenant", "evil", "upload", "UPLOADED"),
                )

    def test_child_table_scoped_through_parent(self, admin_db, db, seeded):
        tenant_a, tenant_b, mid = seeded

        trid = str(uuid.uuid4())
        with admin_db.cursor() as cur:
            cur.execute(
                'INSERT INTO "Transcript" ("id", "meetingId", "fullText", "language", '
                '"wordCount", "durationMs") '
                "VALUES (%s, %s, %s, %s, 2, 0)",
                (trid, mid, "hello world", "en"),
            )

        _set_tenant(db, tenant_b)
        with db.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM "Transcript" WHERE "id" = %s', (trid,))
            assert cur.fetchone()[0] == 0, "child row visible across tenants"

        _set_tenant(db, tenant_a)
        with db.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM "Transcript" WHERE "id" = %s', (trid,))
            assert cur.fetchone()[0] == 1

        with admin_db.cursor() as cur:
            cur.execute('DELETE FROM "Transcript" WHERE "id" = %s', (trid,))
