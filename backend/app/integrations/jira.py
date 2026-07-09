from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime
import httpx
import logging

from app.schemas import Integration, Task
from app.integrations.factory import IntegrationPort, NormalizedWebhookEvent

logger = logging.getLogger(__name__)


class JiraAdapter(IntegrationPort):
    """Jira Cloud integration adapter."""
    
    def __init__(self):
        self.base_url = None
        self.auth = None
        self.project_key = None
        self.issue_type = "Task"
    
    async def _get_client(self, integration: Integration) -> httpx.AsyncClient:
        """Create authenticated HTTP client."""
        config = integration.config
        self.base_url = config.get("base_url", "").rstrip("/")
        self.project_key = config.get("project_key")
        self.issue_type = config.get("issue_type", "Task")
        
        # Jira uses Basic Auth with email and API token
        email = config.get("email")
        api_token = config.get("api_token")
        
        return httpx.AsyncClient(
            base_url=self.base_url,
            auth=(email, api_token),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
    
    async def create_task(self, integration: Integration, task: Task) -> str:
        """Create a Jira issue."""
        async with await self._get_client(integration) as client:
            # Build description with context
            description = self._format_description(task)
            
            # Prepare payload
            payload = {
                "fields": {
                    "project": {"key": self.project_key},
                    "summary": task.title,
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": description}
                                ]
                            }
                        ]
                    },
                    "issuetype": {"name": self.issue_type},
                    "labels": [
                        "meeting-intelligence",
                        f"meeting-{task.meeting_id[:8]}",
                        task.task_type.lower(),
                    ],
                }
            }
            
            # Add assignee if available
            if task.assignee_id and task.assignee:
                # Would need to map internal user to Jira account ID
                # For now, skip assignee
                pass
            
            # Add due date if available
            if task.deadline task.deadline_date:
                payload["fields"]["duedate"] = task.deadline_date.strftime("%Y-%m-%d")
            
            response = await client.post("/rest/api/3/issue", json=payload)
            response.raise_for_status()
            
            data = response.json()
            issue_key = data["key"]
            
            logger.info(f"Created Jira issue {issue_key} for task {task.id}")
            return issue_key
    
    async def update_task(self, integration: Integration, task: Task) -> None:
        """Update a Jira issue."""
        if not task.external_id:
            return
        
        async with await self._get_client(integration) as client:
            # Update fields
            payload = {
                "fields": {}
            }
            
            if task.title:
                payload["fields"]["summary"] = task.title
            
            if task.description:
                payload["fields"]["description"] = {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": self._format_description(task)}
                            ]
                        }
                    ]
                }
            
            if task.deadline_date:
                payload["fields"]["duedate"] = task.deadline_date.strftime("%Y-%m-%d")
            
            if payload["fields"]:
                response = await client.put(
                    f"/rest/api/3/issue/{task.external_id}",
                    json=payload
                )
                response.raise_for_status()
                logger.info(f"Updated Jira issue {task.external_id}")
    
    async def delete_task(self, integration: Integration, external_id: str) -> None:
        """Delete a Jira issue (move to trash)."""
        async with await self._get_client(integration) as client:
            response = await client.delete(f"/rest/api/3/issue/{external_id}")
            response.raise_for_status()
    
    def _format_description(self, task: Task) -> str:
        """Format task description for Jira."""
        parts = [
            f"*Source:* Meeting Intelligence AI",
            f"*Meeting:* {task.meeting_id}",
            f"*Type:* {task.task_type}",
            f"*Confidence:* {task.extraction_confidence:.0%}",
            "",
            f"*Original Quote:*",
            f"_{task.source_quote}_",
            "",
            f"*Description:*",
            task.description,
        ]
        
        if task.assignee_hint:
            parts.insert(3, f"*Suggested Assignee:* {task.assignee_hint}")
        
        if task.deadline_hint:
            parts.insert(4, f"*Suggested Deadline:* {task.deadline_hint}")
        
        return "\n".join(parts)
    
    def normalize_webhook(self, payload: Dict[str, Any]) -> NormalizedWebhookEvent:
        """Convert Jira webhook to normalized event."""
        issue = payload.get("issue", {})
        changelog = payload.get("changelog", {})
        items = changelog.get("items", [])
        
        # Find status change
        status_change = next(
            (item for item in items if item.get("field") == "status"),
            None
        )
        
        status_map = {
            "To Do": "todo",
            "In Progress": "in_progress",
            "In Review": "in_review",
            "Done": "done",
            "Closed": "done",
            "Resolved": "done",
        }
        
        new_status = "unknown"
        if status_change:
            new_status = status_map.get(status_change.get("toString", ""), "unknown")
        elif issue.get("fields", {}).get("status", {}).get("name"):
            new_status = status_map.get(issue["fields"]["status"]["name"], "unknown")
        
        return NormalizedWebhookEvent(
            external_id=issue.get("key"),
            external_url=f"{self.base_url}/browse/{issue.get('key')}" if self.base_url else "",
            status=new_status,
            changed_at=datetime.fromisoformat(payload.get("timestamp", "").replace("Z", "+00:00")),
            raw_payload=payload,
        )
    
    async def verify_webhook_signature(
        self,
        integration: Integration,
        payload: bytes,
        signature: str
    ) -> bool:
        """Verify Jira webhook signature (Jira doesn't use signatures by default)."""
        # Jira webhooks can be configured with a secret
        # For now, return True (implement HMAC verification if secret configured)
        return True
    
    async def test_connection(self, integration: Integration) -> Dict[str, Any]:
        """Test Jira connection."""
        async with await self._get_client(integration) as client:
            response = await client.get("/rest/api/3/myself")
            response.raise_for_status()
            user = response.json()
            return {
                "connected": True,
                "user": user.get("displayName"),
                "email": user.get("emailAddress"),
            }


class AsanaAdapter(IntegrationPort):
    """Asana integration adapter."""
    
    def __init__(self):
        self.base_url = "https://app.asana.com/api/1.0"
        self.access_token = None
        self.workspace_gid = None
        self.project_gid = None
    
    async def _get_client(self, integration: Integration) -> httpx.AsyncClient:
        config = integration.config
        self.access_token = config.get("access_token")
        self.workspace_gid = config.get("workspace_gid")
        self.project_gid = config.get("project_gid")
        
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
            },
            timeout=30.0,
        )
    
    async def create_task(self, integration: Integration, task: Task) -> str:
        async with await self._get_client(integration) as client:
            payload = {
                "data": {
                    "name": task.title,
                    "notes": self._format_description(task),
                    "projects": [self.project_gid] if self.project_gid else [],
                    "workspace": self.workspace_gid,
                    "tags": ["meeting-intelligence", task.task_type.lower()],
                }
            }
            
            if task.deadline_date:
                payload["data"]["due_on"] = task.deadline_date.strftime("%Y-%m-%d")
            
            response = await client.post("/tasks", json=payload)
            response.raise_for_status()
            
            data = response.json()
            task_gid = data["data"]["gid"]
            logger.info(f"Created Asana task {task_gid} for task {task.id}")
            return task_gid
    
    async def update_task(self, integration: Integration, task: Task) -> None:
        if not task.external_id:
            return
        
        async with await self._get_client(integration) as client:
            payload = {"data": {}}
            
            if task.title:
                payload["data"]["name"] = task.title
            if task.description:
                payload["data"]["notes"] = self._format_description(task)
            if task.deadline_date:
                payload["data"]["due_on"] = task.deadline_date.strftime("%Y-%m-%d")
            
            if payload["data"]:
                response = await client.put(f"/tasks/{task.external_id}", json=payload)
                response.raise_for_status()
    
    async def delete_task(self, integration: Integration, external_id: str) -> None:
        async with await self._get_client(integration) as client:
            response = await client.delete(f"/tasks/{external_id}")
            response.raise_for_status()
    
    def _format_description(self, task: Task) -> str:
        parts = [
            f"Source: Meeting Intelligence AI",
            f"Meeting: {task.meeting_id}",
            f"Type: {task.task_type}",
            f"Confidence: {task.extraction_confidence:.0%}",
            "",
            f"Original Quote:",
            f"{task.source_quote}",
            "",
            f"Description:",
            task.description,
        ]
        
        if task.assignee_hint:
            parts.insert(3, f"Suggested Assignee: {task.assignee_hint}")
        if task.deadline_hint:
            parts.insert(4, f"Suggested Deadline: {task.deadline_hint}")
        
        return "\n".join(parts)
    
    def normalize_webhook(self, payload: Dict[str, Any]) -> NormalizedWebhookEvent:
        events = payload.get("events", [])
        # Asana sends array of events
        # For simplicity, handle first event
        event = events[0] if events else {}
        resource = event.get("resource", {})
        
        status_map = {
            "incomplete": "todo",
            "complete": "done",
        }
        
        return NormalizedWebhookEvent(
            external_id=resource.get("gid"),
            external_url=f"https://app.asana.com/0/{resource.get('gid')}",
            status=status_map.get("incomplete", "unknown"),
            changed_at=datetime.utcnow(),
            raw_payload=payload,
        )
    
    async def verify_webhook_signature(
        self,
        integration: Integration,
        payload: bytes,
        signature: str
    ) -> bool:
        # Asana uses X-Hook-Signature header with HMAC-SHA256
        import hmac
        import hashlib
        
        secret = integration.webhook_secret
        if not secret:
            return True
        
        expected = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected, signature)
    
    async def test_connection(self, integration: Integration) -> Dict[str, Any]:
        async with await self._get_client(integration) as client:
            response = await client.get("/users/me")
            response.raise_for_status()
            user = response.json()
            return {"connected": True, "user": user["data"]["name"]}


class LinearAdapter(IntegrationPort):
    """Linear integration adapter."""
    
    def __init__(self):
        self.base_url = "https://api.linear.app/graphql"
        self.api_key = None
        self.team_id = None
    
    async def _execute_query(self, integration: Integration, query: str, variables: Dict = None) -> Dict:
        config = integration.config
        self.api_key = config.get("api_key")
        self.team_id = config.get("team_id")
        
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": self.api_key,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        ) as client:
            response = await client.post("", json={"query": query, "variables": variables})
            response.raise_for_status()
            return response.json()
    
    async def create_task(self, integration: Integration, task: Task) -> str:
        query = """
        mutation IssueCreate($input: IssueCreateInput!) {
            issueCreate(input: $input) {
                success
                issue {
                    id
                    identifier
                }
            }
        }
        """
        
        description = self._format_description(task)
        
        variables = {
            "input": {
                "title": task.title,
                "description": description,
                "teamId": self.team_id,
                "labelIds": [],  # Would need to create/get labels
            }
        }
        
        if task.deadline_date:
            variables["input"]["dueDate"] = task.deadline_date.strftime("%Y-%m-%d")
        
        result = await self._execute_query(integration, query, variables)
        
        if result.get("data", {}).get("issueCreate", {}).get("success"):
            issue = result["data"]["issueCreate"]["issue"]
            issue_id = issue["identifier"]  # e.g., "ENG-123"
            logger.info(f"Created Linear issue {issue_id} for task {task.id}")
            return issue_id
        
        raise Exception(f"Failed to create Linear issue: {result}")
    
    async def update_task(self, integration: Integration, task: Task) -> None:
        if not task.external_id:
            return
        
        # Linear uses identifier like "ENG-123"
        query = """
        mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $id, input: $input) {
                success
                issue {
                    id
                }
            }
        }
        """
        
        variables = {
            "id": task.external_id,
            "input": {}
        }
        
        if task.title:
            variables["input"]["title"] = task.title
        if task.description:
            variables["input"]["description"] = self._format_description(task)
        
        await self._execute_query(integration, query, variables)
    
    async def delete_task(self, integration: Integration, external_id: str) -> None:
        query = """
        mutation IssueDelete($id: String!) {
            issueDelete(id: $id) {
                success
            }
        }
        """
        await self._execute_query(integration, query, {"id": external_id})
    
    def _format_description(self, task: Task) -> str:
        parts = [
            f"**Source:** Meeting Intelligence AI",
            f"**Meeting:** {task.meeting_id}",
            f"**Type:** {task.task_type}",
            f"**Confidence:** {task.extraction_confidence:.0%}",
            "",
            f"**Original Quote:**",
            f"> {task.source_quote}",
            "",
            f"**Description:**",
            task.description,
        ]
        
        if task.assignee_hint:
            parts.insert(3, f"**Suggested Assignee:** {task.assignee_hint}")
        if task.deadline_hint:
            parts.insert(4, f"**Suggested Deadline:** {task.deadline_hint}")
        
        return "\n".join(parts)
    
    def normalize_webhook(self, payload: Dict[str, Any]) -> NormalizedWebhookEvent:
        # Linear webhook format
        action = payload.get("action")
        data = payload.get("data", {})
        
        status_map = {
            "unstarted": "todo",
            "started": "in_progress",
            "completed": "done",
            "canceled": "cancelled",
        }
        
        return NormalizedWebhookEvent(
            external_id=data.get("identifier"),
            external_url=data.get("url"),
            status=status_map.get(data.get("state", {}).get("name", ""), "unknown"),
            changed_at=datetime.fromisoformat(payload.get("createdAt", "").replace("Z", "+00:00")),
            raw_payload=payload,
        )
    
    async def verify_webhook_signature(
        self,
        integration: Integration,
        payload: bytes,
        signature: str
    ) -> bool:
        # Linear uses Linear-Signature header with HMAC-SHA256
        import hmac
        import hashlib
        
        secret = integration.webhook_secret
        if not secret:
            return True
        
        expected = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected, signature)
    
    async def test_connection(self, integration: Integration) -> Dict[str, Any]:
        query = "{ viewer { id name email } }"
        result = await self._execute_query(integration, query)
        user = result.get("data", {}).get("viewer", {})
        return {"connected": True, "user": user.get("name")}


class SlackAdapter(IntegrationPort):
    """Slack integration adapter for notifications."""
    
    def __init__(self):
        self.bot_token = None
        self.signing_secret = None
        self.default_channel = None
    
    async def _get_client(self, integration: Integration) -> httpx.AsyncClient:
        config = integration.config
        self.bot_token = config.get("bot_token")
        self.default_channel = config.get("default_channel")
        
        return httpx.AsyncClient(
            base_url="https://slack.com/api",
            headers={
                "Authorization": f"Bearer {self.bot_token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
    
    async def create_task(self, integration: Integration, task: Task) -> str:
        """Post task as message to Slack channel."""
        async with await self._get_client(integration) as client:
            blocks = self._format_slack_message(task)
            
            payload = {
                "channel": self.default_channel,
                "blocks": blocks,
                "text": f"New task: {task.title}",
            }
            
            response = await client.post("chat.postMessage", json=payload)
            response.raise_for_status()
            
            data = response.json()
            if data.get("ok"):
                ts = data["ts"]
                logger.info(f"Posted task to Slack: {ts}")
                return ts
            
            raise Exception(f"Failed to post to Slack: {data}")
    
    async def update_task(self, integration: Integration, task: Task) -> None:
        # Slack doesn't really support updating messages the same way
        # Could post a follow-up message or update the original
        pass
    
    async def delete_task(self, integration: Integration, external_id: str) -> None:
        async with await self._get_client(integration) as client:
            # Would need channel_id to delete
            pass
    
    def _format_slack_message(self, task: Task) -> list:
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"📋 New {task.task_type.replace('_', ' ').title()}",
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Title:*\n{task.title}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Meeting:*\n{task.meeting_id[:8]}..."
                    }
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Description:*\n{task.description}"
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Confidence: {task.extraction_confidence:.0%} | Source: \"{task.source_quote[:100]}...\""
                    }
                ]
            }
        ]
        
        if task.assignee_hint:
            blocks.insert(2, {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Suggested Assignee:*\n{task.assignee_hint}"
                    }
                ]
            })
        
        if task.deadline_hint:
            blocks.insert(3, {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Suggested Deadline:*\n{task.deadline_hint}"
                    }
                ]
            })
        
        return blocks
    
    def normalize_webhook(self, payload: Dict[str, Any]) -> NormalizedWebhookEvent:
        # Slack event format
        event = payload.get("event", {})
        return NormalizedWebhookEvent(
            external_id=event.get("ts"),
            external_url="",
            status="received",
            changed_at=datetime.fromtimestamp(float(event.get("ts", 0))),
            raw_payload=payload,
        )
    
    async def verify_webhook_signature(
        self,
        integration: Integration,
        payload: bytes,
        signature: str
    ) -> bool:
        # Slack uses X-Slack-Signature with HMAC-SHA256
        import hmac
        import hashlib
        
        secret = integration.webhook_secret or self.signing_secret
        if not secret:
            return True
        
        # Slack signature format: v0=...
        timestamp = signature.split(",")[0].split("=")[1]
        sig_hash = signature.split("v0=")[1]
        
        basestring = f"v0:{timestamp}:{payload.decode()}"
        expected = hmac.new(
            secret.encode(),
            basestring.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(f"v0={expected}", signature)
    
    async def test_connection(self, integration: Integration) -> Dict[str, Any]:
        async with await self._get_client(integration) as client:
            response = await client.post("auth.test")
            response.raise_for_status()
            data = response.json()
            return {"connected": data.get("ok"), "team": data.get("team")}


# NormalizedWebhookEvent (defined in factory but also needed here)
from pydantic import BaseModel
from typing import Optional

class NormalizedWebhookEvent(BaseModel):
    external_id: str
    external_url: str
    status: str
    changed_at: datetime
    raw_payload: Dict[str, Any]