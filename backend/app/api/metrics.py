from fastapi import APIRouter, Depends
from typing import List, Dict, Any
from datetime import datetime, timedelta

from app.db.prisma import get_db

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("")
async def get_metrics(
    db=Depends(get_db),
):
    """
    Team accountability metrics — computed live from the database.
    Every figure here is a real aggregate; nothing is hardcoded.
    """
    total_meetings = await db.meeting.count()
    total_tasks = await db.task.count()

    # Verification funnel
    verified_tasks = await db.task.count(where={"verificationStatus": "VERIFIED"})
    verification_rate = round((verified_tasks / total_tasks * 100) if total_tasks > 0 else 0, 1)

    # Funnel data (real status counts)
    funnel_data = [
        {"stage": "Extracted", "count": await db.task.count(where={"status": "EXTRACTED"})},
        {"stage": "Verified", "count": await db.task.count(where={"status": "VERIFIED"})},
        {"stage": "Assigned", "count": await db.task.count(where={"status": "ASSIGNED"})},
        {"stage": "Synced", "count": await db.task.count(where={"status": "SYNCED"})},
        {"stage": "Completed", "count": await db.task.count(where={"status": "COMPLETED"})},
    ]

    # Avg time-to-sync: mean latency between task creation and first external
    # sync for tasks that have been synced (null until real syncs exist).
    synced_tasks = await db.task.find_many(
        where={
            "status": {"in": ["SYNCED", "COMPLETED"]},
            "lastSyncedAt": {"not": None},
        },
        select={"createdAt": True, "lastSyncedAt": True},
        take=500,
        order={"createdAt": "desc"},
    )
    sync_durations = [
        (t.lastSyncedAt - t.createdAt).total_seconds() / 3600
        for t in synced_tasks
        if t.lastSyncedAt and t.lastSyncedAt > t.createdAt
    ]
    avg_time_to_sync = round(sum(sync_durations) / len(sync_durations), 1) if sync_durations else None

    # Extraction accuracy trend by week: share of tasks created that week that
    # passed verification. Precision proxy = verified / (verified + dismissed).
    accuracy_by_week = []
    now = datetime.utcnow()
    for weeks_back in range(3, -1, -1):
        week_start = now - timedelta(weeks=weeks_back + 1)
        week_end = now - timedelta(weeks=weeks_back)
        created = await db.task.count(
            where={"createdAt": {"gte": week_start, "lt": week_end}}
        )
        verified_wk = await db.task.count(
            where={
                "createdAt": {"gte": week_start, "lt": week_end},
                "verificationStatus": "VERIFIED",
            }
        )
        dismissed_wk = await db.task.count(
            where={
                "createdAt": {"gte": week_start, "lt": week_end},
                "status": "DISMISSED",
            }
        )
        denom = verified_wk + dismissed_wk
        precision = round(verified_wk / denom, 2) if denom else 0.0
        recall_proxy = round(verified_wk / created, 2) if created else 0.0
        f1 = (
            round(2 * precision * recall_proxy / (precision + recall_proxy), 2)
            if (precision + recall_proxy) else 0.0
        )
        accuracy_by_week.append({
            "week": f"Week -{weeks_back}" if weeks_back else "This week",
            "tasks_created": created,
            "verified": verified_wk,
            "precision": precision,
            "recall": recall_proxy,
            "f1": f1,
        })

    # Team performance: per-user real counts from assigned tasks.
    users = await db.user.find_many(
        select={"id": True, "fullName": True},
        take=100,
    )
    team_performance = []
    for user in users:
        assigned = await db.task.count(where={"assigneeId": user.id})
        completed = await db.task.count(
            where={"assigneeId": user.id, "status": "COMPLETED"}
        )
        overdue = await db.task.count(
            where={
                "assigneeId": user.id,
                "deadlineDate": {"lt": now},
                "status": {"notIn": ["COMPLETED", "DISMISSED"]},
            }
        )
        meetings_attended = await db.attendee.count(where={"userId": user.id})
        team_performance.append({
            "teamMember": user.fullName,
            "meetingsAttended": meetings_attended,
            "tasksAssigned": assigned,
            "tasksCompleted": completed,
            "overdueRate": round(overdue / assigned * 100) if assigned else 0,
        })
    # Only include members with actual assignments
    team_performance = [m for m in team_performance if m["tasksAssigned"] > 0]

    return {
        "totalMeetings": total_meetings,
        "totalTasksExtracted": total_tasks,
        "verificationRate": verification_rate,
        "avgTimeToSync": avg_time_to_sync,
        "accuracyByWeek": accuracy_by_week,
        "funnelData": funnel_data,
        "teamPerformance": team_performance,
    }
