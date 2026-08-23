from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from typing import Dict, List, Set
from uuid import UUID
import json
import asyncio
import logging

from app.db.prisma import get_prisma
from app.core.config import settings

router = APIRouter(prefix="/ws", tags=["WebSocket"])

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections per tenant."""
    
    def __init__(self):
        # tenant_id -> {user_id -> [WebSocket]}
        self.active_connections: Dict[str, Dict[str, List[WebSocket]]] = {}
        # WebSocket -> (tenant_id, user_id)
        self.connection_info: Dict[WebSocket, tuple] = {}
    
    async def connect(self, websocket: WebSocket, tenant_id: str, user_id: str):
        await websocket.accept()
        
        if tenant_id not in self.active_connections:
            self.active_connections[tenant_id] = {}
        if user_id not in self.active_connections[tenant_id]:
            self.active_connections[tenant_id][user_id] = []
        
        self.active_connections[tenant_id][user_id].append(websocket)
        self.connection_info[websocket] = (tenant_id, user_id)
        
        logger.info(f"WebSocket connected: tenant={tenant_id}, user={user_id}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.connection_info:
            tenant_id, user_id = self.connection_info[websocket]
            
            if tenant_id in self.active_connections:
                if user_id in self.active_connections[tenant_id]:
                    if websocket in self.active_connections[tenant_id][user_id]:
                        self.active_connections[tenant_id][user_id].remove(websocket)
                    
                    if not self.active_connections[tenant_id][user_id]:
                        del self.active_connections[tenant_id][user_id]
                
                if not self.active_connections[tenant_id]:
                    del self.active_connections[tenant_id]
            
            del self.connection_info[websocket]
            logger.info(f"WebSocket disconnected: tenant={tenant_id}, user={user_id}")
    
    async def send_personal_message(self, message: dict, tenant_id: str, user_id: str):
        """Send message to a specific user."""
        if tenant_id in self.active_connections:
            if user_id in self.active_connections[tenant_id]:
                for ws in self.active_connections[tenant_id][user_id]:
                    try:
                        await ws.send_json(message)
                    except Exception:
                        pass  # Connection likely closed
    
    async def broadcast_to_tenant(self, message: dict, tenant_id: str):
        """Broadcast message to all users in a tenant."""
        if tenant_id in self.active_connections:
            for user_id, connections in self.active_connections[tenant_id].items():
                for ws in connections:
                    try:
                        await ws.send_json(message)
                    except Exception:
                        pass
    
    async def broadcast_task_update(self, tenant_id: str, task_data: dict):
        """Broadcast task update to all users in tenant."""
        message = {
            "type": "task_update",
            "payload": task_data,
        }
        await self.broadcast_to_tenant(message, tenant_id)
    
    async def broadcast_meeting_update(self, tenant_id: str, meeting_data: dict):
        """Broadcast meeting update to all users in tenant."""
        message = {
            "type": "meeting_update",
            "payload": meeting_data,
        }
        await self.broadcast_to_tenant(message, tenant_id)


manager = ConnectionManager()


async def get_tenant_user_from_token(token: str) -> tuple[str, str]:
    """Verify the WebSocket token with the shared verifier and return identity."""
    from app.security.auth import verify_access_token, AuthError

    try:
        verified = await verify_access_token(token)
        return verified.tenant_id, verified.user_id
    except AuthError as e:
        raise ValueError(f"Invalid websocket token: {e}")


@router.websocket("")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
):
    """WebSocket endpoint for real-time updates."""
    tenant_id, user_id = await get_tenant_user_from_token(token)
    
    await manager.connect(websocket, tenant_id, user_id)
    
    try:
        # Send welcome message
        await websocket.send_json({
            "type": "connected",
            "payload": {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "message": "Connected to AMI real-time updates",
            }
        })
        
        # Keep connection alive and handle incoming messages
        while True:
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                await handle_websocket_message(websocket, tenant_id, user_id, message)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "payload": {"message": "Invalid JSON"},
                })
    
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


async def handle_websocket_message(
    websocket: WebSocket,
    tenant_id: str,
    user_id: str,
    message: dict,
):
    """Handle incoming WebSocket messages."""
    msg_type = message.get("type")
    
    if msg_type == "ping":
        await websocket.send_json({"type": "pong", "payload": {}})
    
    elif msg_type == "subscribe":
        # Subscribe to specific meeting or events
        pass
    
    elif msg_type == "task_action":
        # Handle task actions from UI (verify, assign, etc.)
        pass
    
    else:
        await websocket.send_json({
            "type": "error",
            "payload": {"message": f"Unknown message type: {msg_type}"},
        })


# ─── Helper functions for other services to broadcast updates ───

async def broadcast_task_created(tenant_id: str, task: dict):
    """Broadcast task creation event."""
    await manager.broadcast_to_tenant({
        "type": "task_created",
        "payload": task,
    }, tenant_id)


async def broadcast_task_updated(tenant_id: str, task: dict):
    """Broadcast task update event."""
    await manager.broadcast_to_tenant({
        "type": "task_updated",
        "payload": task,
    }, tenant_id)


async def broadcast_task_deleted(tenant_id: str, task_id: str):
    """Broadcast task deletion event."""
    await manager.broadcast_to_tenant({
        "type": "task_deleted",
        "payload": {"task_id": task_id},
    }, tenant_id)


async def broadcast_meeting_status_changed(tenant_id: str, meeting_id: str, status: str):
    """Broadcast meeting status change."""
    await manager.broadcast_to_tenant({
        "type": "meeting_status_changed",
        "payload": {"meeting_id": meeting_id, "status": status},
    }, tenant_id)


async def broadcast_transcript_ready(tenant_id: str, meeting_id: str, transcript_id: str):
    """Broadcast transcript completion."""
    await manager.broadcast_to_tenant({
        "type": "transcript_ready",
        "payload": {"meeting_id": meeting_id, "transcript_id": transcript_id},
    }, tenant_id)