import requests
import jwt
from datetime import datetime, timedelta

# Create a valid token
token = jwt.encode(
    {
        "sub": "06f17215-8452-4297-b9a4-4c5614dc54d3",
        "email": "test@e2e.com",
        "tenant_id": "f235e027-a68a-4e75-b77d-1a04d09eafc0",
        "role": "admin",
        "exp": datetime.utcnow() + timedelta(hours=1)
    },
    "dev_secret",
    algorithm="HS256"
)

headers = {"Authorization": f"Bearer {token}"}
resp = requests.get("http://127.0.0.1:8000/api/v1/tasks", headers=headers)
import json
print(json.dumps(resp.json(), indent=2))
