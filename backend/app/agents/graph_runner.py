from langgraph.graph import StateGraph, END
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver
from typing import Dict, Any, Optional, AsyncGenerator
import logging
import asyncio
from uuid import uuid4

from app.agents.schemas import ExtractionState
from app.agents.extraction_graph import (
    build_extraction_graph,
    run_extraction_pipeline,
    resume_extraction_pipeline,
    get_pipeline_state,
)

logger = logging.getLogger(__name__)


# ─── Build the LangGraph (re-export) ───
# The graph is built in extraction_graph.py with interrupt support


# ─── Run Extraction Pipeline ───

async def run_extraction_pipeline_wrapper(
    meeting_id: str,
    tenant_id: str,
    user_id: str,
    meeting_context: str = "",
    transcript_chunks: list = None,
    pipeline_run_id: Optional[str] = None,
) -> ExtractionState:
    """Run the full extraction pipeline for a meeting."""
    return await run_extraction_pipeline(
        meeting_id=meeting_id,
        tenant_id=tenant_id,
        user_id=user_id,
        meeting_context=meeting_context,
        transcript_chunks=transcript_chunks,
        pipeline_run_id=pipeline_run_id,
    )


async def resume_extraction_pipeline_wrapper(
    meeting_id: str,
    human_feedback: Dict[str, Any],
) -> ExtractionState:
    """Resume the extraction pipeline after HITL interrupt."""
    return await resume_extraction_pipeline(meeting_id, human_feedback)


async def get_pipeline_state_wrapper(meeting_id: str) -> Optional[ExtractionState]:
    """Get current pipeline state for a meeting."""
    return await get_pipeline_state(meeting_id)


# ─── Streaming Version (for progress updates) ───

async def stream_extraction_pipeline(
    meeting_id: str,
    tenant_id: str,
    user_id: str,
    meeting_context: str = "",
    transcript_chunks: list = None,
    pipeline_run_id: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Stream the extraction pipeline with progress updates."""
    
    initial_state = ExtractionState(
        meeting_id=meeting_id,
        tenant_id=tenant_id,
        user_id=user_id,
        meeting_context=meeting_context,
        transcript_chunks=transcript_chunks or [],
        pipeline_run_id=pipeline_run_id or str(uuid4()),
    )
    
    graph = build_extraction_graph()
    config = {"configurable": {"thread_id": meeting_id}}
    
    try:
        async for event in graph.astream(initial_state, config=config):
            # event contains the node name and updated state
            for node_name, state_update in event.items():
                # Check if this is an interrupt
                if state_update.get("interrupted"):
                    yield {
                        "type": "interrupt",
                        "node": node_name,
                        "interrupt_reason": state_update.get("interrupt_reason"),
                        "interrupt_payload": state_update.get("interrupt_payload"),
                        "progress": _calculate_progress(node_name),
                    }
                else:
                    yield {
                        "type": "progress",
                        "node": node_name,
                        "state": state_update,
                        "progress": _calculate_progress(node_name),
                    }
                    
    except Exception as e:
        logger.error(f"Streaming extraction failed for {meeting_id}: {e}")
        yield {
            "type": "error",
            "node": "unknown",
            "error": str(e),
            "progress": 0.0,
        }


def _calculate_progress(node_name: str) -> float:
    """Calculate pipeline progress percentage."""
    progress_map = {
        "chunking": 0.1,
        "extraction": 0.3,
        "deduplication": 0.5,
        "verification": 0.7,
        "entity_resolution": 0.85,
        "persistence": 1.0,
    }
    return progress_map.get(node_name, 0.0)


# ─── HITL Helper Functions ───

def create_hitl_approval_feedback(task_id: str, approved: bool = True) -> Dict[str, Any]:
    """Create human feedback for task approval."""
    return {
        "action": "APPROVE" if approved else "REJECT",
        "task_id": task_id,
        "timestamp": asyncio.get_event_loop().time(),
    }


def create_hitl_modification_feedback(
    task_id: str,
    modifications: Dict[str, Any],
) -> Dict[str, Any]:
    """Create human feedback with task modifications."""
    return {
        "action": "MODIFY",
        "task_id": task_id,
        "modifications": modifications,
        "timestamp": asyncio.get_event_loop().time(),
    }


# ─── Pipeline Status Check ───

async def check_pipeline_status(meeting_id: str) -> Dict[str, Any]:
    """Check the current status of a pipeline."""
    state = await get_pipeline_state_wrapper(meeting_id)
    
    if not state:
        return {"status": "not_found", "meeting_id": meeting_id}
    
    if state.interrupted:
        return {
            "status": "interrupted",
            "meeting_id": meeting_id,
            "interrupt_node": state.interrupt_node,
            "interrupt_reason": state.interrupt_reason,
            "interrupt_payload": state.interrupt_payload,
            "progress": _calculate_progress(state.interrupt_node or "unknown"),
        }
    
    # Determine completion status
    if state.final_tasks:
        return {
            "status": "completed",
            "meeting_id": meeting_id,
            "tasks_created": len(state.final_tasks),
            "errors": state.errors,
            "progress": 1.0,
        }
    
    if state.errors:
        return {
            "status": "failed",
            "meeting_id": meeting_id,
            "errors": state.errors,
            "progress": _get_last_completed_node_progress(state),
        }
    
    return {
        "status": "running",
        "meeting_id": meeting_id,
        "progress": _get_last_completed_node_progress(state),
    }


def _get_last_completed_node_progress(state: ExtractionState) -> float:
    """Estimate progress based on what state fields are populated."""
    if state.final_tasks:
        return 1.0
    if state.verified_tasks:
        return 0.85
    if state.deduplicated_tasks:
        return 0.7
    if state.proposed_tasks:
        return 0.5
    if state.transcript_chunks:
        return 0.3
    return 0.1