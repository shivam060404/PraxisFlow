import asyncio
import httpx
import uuid
from jose import jwt
from datetime import datetime, timedelta
import time
import json
import os

# Configuration
API_URL = "http://localhost:8000/api/v1"
JWT_SECRET = os.environ.get("JWT_SECRET", "dev_secret_change_in_production")
ALGORITHM = "HS256"

# Create a deterministic tenant and user
TENANT_ID = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())

# Generate JWT Token
def generate_token():
    payload = {
        "sub": USER_ID,
        "tenant_id": TENANT_ID,
        "exp": datetime.utcnow() + timedelta(hours=1)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)

async def run_test():
    token = generate_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    print(f"[*] Generated Token: {token[:20]}...")
    print(f"[*] Tenant ID: {TENANT_ID}")
    
    async with httpx.AsyncClient() as client:
        # 1. Check health
        print("[*] Checking Health...")
        health = await client.get("http://localhost:8000/health")
        print("Health:", health.status_code)
        
        # 2. Seed Tenant and User
        print("[*] Seeding Tenant and User in DB...")
        import sys
        sys.path.insert(0, os.getcwd())
        from app.db.prisma import get_prisma
        db = await get_prisma()
        
        # We must disable RLS or set context manually if it's Prisma
        try:
            await db.tenant.upsert(
                where={"id": TENANT_ID},
                data={
                    "create": {"id": TENANT_ID, "name": "E2E Test Tenant", "slug": f"e2e-tenant-{TENANT_ID[:8]}", "plan": "enterprise", "status": "active"},
                    "update": {}
                }
            )
            await db.user.upsert(
                where={"id": USER_ID},
                data={
                    "create": {
                        "id": USER_ID,
                        "email": "test@e2e.com",
                        "fullName": "Test User",
                        "role": "admin",
                        "tenant": {"connect": {"id": TENANT_ID}}
                    },
                    "update": {}
                }
            )
        except Exception as e:
            print(f"Failed to seed DB: {e}")
            
        print("[*] Uploading meeting audio...")
        files = {'file': ('sample.wav', open('/tmp/sample.wav', 'rb'), 'audio/wav')}
        data = {
            'title': 'Project Sync Meeting',
            'description': 'Weekly sync to discuss blockers and action items',
            'scheduled_at': datetime.utcnow().isoformat() + "Z",
            'tenant_id': TENANT_ID
        }
        
        response = await client.post(f"{API_URL}/meetings/upload", headers=headers, data=data, files=files)
        if response.status_code != 201:
            print("Upload failed:", response.status_code, response.text)
            return
            
        meeting = response.json()
        meeting_id = meeting['id']
        print(f"[*] Meeting created successfully: {meeting_id}")
        
        # 3. Trigger processing if not auto triggered
        print("[*] Triggering processing...")
        proc_resp = await client.post(f"{API_URL}/meetings/{meeting_id}/process", headers=headers)
        print("Process Trigger:", proc_resp.status_code, proc_resp.text)
        
        # 4. Poll for processing status
        print("[*] Polling meeting status...")
        for i in range(30):  # Wait up to 60 seconds
            await asyncio.sleep(2)
            resp = await client.get(f"{API_URL}/meetings/{meeting_id}/status", headers=headers)
            if resp.status_code == 200:
                status = resp.json()
                print(f"  -> Status: {status['status']} (Tasks: {status['tasks_count']})")
                if status['status'] == 'COMPLETED':
                    print("[+] Processing completed successfully!")
                    break
                elif status['status'] == 'ERROR':
                    print("[-] Processing failed!")
                    break
            else:
                print("Failed to get status", resp.status_code, resp.text)
        
        # 5. Fetch Tasks
        print("[*] Fetching generated tasks...")
        resp = await client.get(f"{API_URL}/tasks?meeting_id={meeting_id}", headers=headers)
        if resp.status_code == 200:
            tasks_data = resp.json()
            tasks = tasks_data.get('items', [])
            print(f"[+] Found {len(tasks)} tasks:")
            for task in tasks:
                print("RAW TASK:", task)
                print(f"  - [{task.get('taskType')}] {task.get('title')}")
                print(f"    Desc: {task.get('description')}")
                print(f"    Assignee Hint: {task.get('assigneeHint')}")
                print(f"    Verification Status: {task.get('verificationStatus')}")
                print("---")
        else:
            print("Failed to fetch tasks", resp.status_code, resp.text)

if __name__ == "__main__":
    asyncio.run(run_test())
