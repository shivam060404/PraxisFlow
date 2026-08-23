"""
Seed a development tenant + admin user so the API accepts tokens minted for
them. Run after `prisma db push` / `prisma migrate`:

    python scripts/seed_dev.py

Idempotent: safe to run repeatedly.
"""

import asyncio
import sys

TENANT_ID = "00000000-0000-0000-0000-000000000001"
ADMIN_EMAIL = "admin@dev.local"


async def main() -> None:
    from prisma import Prisma

    db = Prisma()
    await db.connect()

    tenant = await db.tenant.find_unique(where={"id": TENANT_ID})
    if not tenant:
        tenant = await db.tenant.create(
            data={
                "id": TENANT_ID,
                "name": "Development Tenant",
                "slug": "dev",
                "plan": "enterprise",
                "status": "active",
            }
        )
        print(f"Created tenant {tenant.id}")
    else:
        print(f"Tenant {tenant.id} already exists")

    user = await db.user.find_first(
        where={"tenantId": TENANT_ID, "email": ADMIN_EMAIL}
    )
    if not user:
        user = await db.user.create(
            data={
                "tenantId": TENANT_ID,
                "email": ADMIN_EMAIL,
                "fullName": "Dev Admin",
                "role": "tenant_admin",
                "status": "ACTIVE",
            }
        )
        print(f"Created admin user {user.id} ({user.email})")
    else:
        print(f"Admin user already exists ({user.email})")

    print("\nMint a token for this identity:")
    print(
        "python -c \""
        "import os, time; from jose import jwt; "
        "print(jwt.encode({'sub': '" + user.id + "', "
        "'tenant_id': '" + TENANT_ID + "', 'role': 'tenant_admin', "
        "'exp': int(time.time()) + 86400}, "
        "os.getenv('JWT_SECRET', 'dev_secret_change_in_production'), "
        "algorithm='HS256'))\""
    )

    await db.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Seed failed: {e}", file=sys.stderr)
        print("Is Postgres running and has 'prisma db push' been executed?", file=sys.stderr)
        sys.exit(1)
