from fastapi import APIRouter, Depends
from typing import List, Dict, Any
from datetime import datetime, timedelta

from app.db.prisma import get_db

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("")
async def get_metrics(
    db=Depends(get_db),
):
    """Get team accountability metrics."""
    # Get basic counts
    total_meetings = await db.meeting.count()
    total_tasks = await db.task.count()
    
    # Verification rate
    verified_tasks = await db.task.count(where={"verificationStatus": "VERIFIED"})
    verification_rate = round((verified_tasks / total_tasks * 100) if total_tasks > 0 else 0, 1)
    
    # Avg time to sync (mock for now)
    avg_time_to_sync = 12
    
    # Accuracy by week (mock data)
    accuracy_by_week = [
        {"week": "Week 1", "precision": 0.72, "recall": 0.68, "f1": 0.70},
        {"week": "Week 2", "precision": 0.75, "recall": 0.71, "f1": 0.73},
        {"week": "Week 3", "precision": 0.78, "recall": 0.74, "f1": 0.76},
        {"week": "Week 4", "precision": 0.81, "recall": 0.77, "f1": 0.79},
    ]
    
    # Funnel data
    funnel_data = [
        {"stage": "Extracted", "count": await db.task.count(where={"status": "EXTRACTED"})},
        {"stage": "Verified", "count": await db.task.count(where={"status": "VERIFIED"})},
        {"stage": "Assigned", "count": await db.task.count(where={"status": "ASSIGNED"})},
        {"stage": "Synced", "count": await db.task.count(where={"status": "SYNCED"})},
        {"stage": "Completed", "count": await db.task.count(where={"status": "COMPLETED"})},
    ]
    
    # Team performance (mock data)
    team_performance = [
        {"teamMember": "Sarah Chen", "meetingsAttended": 24, "tasksAssigned": 45, "tasksCompleted": 38, "avgCompletionTime": 2.3, "overdueRate": 5},
        {"teamMember": "Mike Johnson", "meetingsAttended": 18, "tasksAssigned": 32, "tasksCompleted": 25, "avgCompletionTime": 3.1, "overdueRate": 12},
        {"teamMember": "Emily Davis", "meetingsAttended": 31, "tasksAssigned": 58, "tasksCompleted": 52, "avgCompletionTime": 1.8, "overdueRate": 3},
        {"teamMember": "James Wilson", "meetingsAttended": 15, "tasksAssigned": 28, "tasksCompleted": 19, "avgCompletionTime": 4.2, "overdueRate": 25},
        {"teamMember": "Lisa Anderson", "meetingsAttended": 22, "tasksAssigned": 41, "tasksCompleted": 35, "avgCompletionTime": 2.7, "overdueRate": 8},
    ]
    
    return {
        "totalMeetings": total_meetings,
        "totalTasksExtracted": total_tasks,
        "verificationRate": verification_rate,
        "avgTimeToSync": avg_time_to_sync,
        "accuracyByWeek": accuracy_by_week,
        "funnelData": funnel_data,
        "teamPerformance": team_performance,
    }