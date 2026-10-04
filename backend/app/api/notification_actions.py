"""Unauthenticated, signed HITL links embedded in native notifications."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.prisma import get_db
from app.services.notifications import verify_action_token

router = APIRouter(prefix="/notifications/actions", tags=["Notifications"])


@router.get("/{action}")
async def apply_notification_action(
    action: str,
    token: str = Query(...),
    db=Depends(get_db),
):
    """Verify/reject a task from Slack or Teams.

    The token is the authentication and idempotency key. Replaying a link is
    safe: once the task reaches the requested terminal state, no second audit
    event is written.
    """
    if action not in {"verify", "reject"}:
        raise HTTPException(status_code=404, detail="Unknown notification action")
    try:
        claims = verify_action_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if claims["action"] != action:
        raise HTTPException(status_code=401, detail="Action does not match token")

    task = await db.task.find_first(
        where={"id": claims["task_id"], "tenantId": claims["tenant_id"]}
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    target_status = "VERIFIED" if action == "verify" else "DISMISSED"
    target_verification = "VERIFIED" if action == "verify" else "FAILED"
    if task.status == target_status and task.verificationStatus == target_verification:
        return {"status": "already_applied", "action": action, "task_id": task.id}

    # Restrict transitions to reviewable work. This update is atomic, so two
    # concurrent clicks cannot both create an action audit record.
    changed = await db.task.update_many(
        where={
            "id": task.id,
            "tenantId": claims["tenant_id"],
            "status": {"in": ["EXTRACTED", "PENDING_REVIEW"]},
        },
        data={"status": target_status, "verificationStatus": target_verification,
              "verificationReasoning": f"Human {action} via signed notification action"},
    )
    if not changed:
        refreshed = await db.task.find_first(
            where={"id": task.id, "tenantId": claims["tenant_id"]}
        )
        if refreshed and refreshed.status == target_status:
            return {"status": "already_applied", "action": action, "task_id": task.id}
        raise HTTPException(status_code=409, detail="Task is no longer awaiting review")

    await db.taskauditlog.create(
        data={"taskId": task.id, "previousStatus": task.status,
              "newStatus": target_status, "changedBy": "signed_notification",
              "reason": f"Human {action} via signed notification action",
              "metadata": {"action_token": token[:16]}},
    )
    return {"status": "applied", "action": action, "task_id": task.id}
