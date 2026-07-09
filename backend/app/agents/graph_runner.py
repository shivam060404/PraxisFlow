from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from typing import Dict, Any
import logging

from app.agents.schemas import ExtractionState
from app.agents.extraction_graph import (
    chunking_node,
    extraction_node,
    deduplication_node,
    verification_node,
    entity_resolution_node,
    persistence_node,
)

logger = logging.getLogger(__name__)


# ─── Build the LangGraph ───

def build_extraction_graph() -> StateGraph:
    """Build the extraction pipeline graph."""
    
    workflow = StateGraph(ExtractionState)
    
    # Add nodes
    workflow.add_node("chunking", chunking_node)
    workflow.add_node("extraction", extraction_node)
    workflow.add_node("deduplication", deduplication_node)
    workflow.add_node("verification", verification_node)
    workflow.add_node("entity_resolution", entity_resolution_node)
    workflow.add_node("persistence", persistence_node)
    
    # Define edges
    workflow.set_entry_point("chunking")
    
    workflow.add_edge("chunking", "extraction")
    workflow.add_edge("extraction", "deduplication")
    workflow.add_edge("deduplication", "verification")
    workflow.add_edge("verification", "entity_resolution")
    workflow.add_edge("entity_resolution", "persistence")
    workflow.add_edge("persistence", END)
    
    # Compile with memory saver for checkpointing
    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)
    
    return app


# ─── Run Extraction Pipeline ───

async def run_extraction_pipeline(
    meeting_id: str,
    tenant_id: str,
    meeting_context: str = "",
    transcript_chunks: list = None,
) -> ExtractionState:
    """Run the full extraction pipeline for a meeting."""
    
    # Initialize state
    initial_state = ExtractionState(
        meeting_id=meeting_id,
        tenant_id=tenant_id,
        meeting_context=meeting_context,
        transcript_chunks=transcript_chunks or [],
    )
    
    # Build and run graph
    graph = build_extraction_graph()
    
    # Config for checkpointing
    config = {"configurable": {"thread_id": meeting_id}}
    
    try:
        final_state = await graph.ainvoke(initial_state, config=config)
        logger.info(f"Extraction pipeline completed for meeting {meeting_id}")
        return final_state
    except Exception as e:
        logger.error(f"Extraction pipeline failed for meeting {meeting_id}: {e}")
        raise


# ─── Streaming Version (for progress updates) ───

async def stream_extraction_pipeline(
    meeting_id: str,
    tenant_id: str,
    meeting_context: str = "",
    transcript_chunks: list = None,
):
    """Stream the extraction pipeline with progress updates."""
    
    initial_state = ExtractionState(
        meeting_id=meeting_id,
        tenant_id=tenant_id,
        meeting_context=meeting_context,
        transcript_chunks=transcript_chunks or [],
    )
    
    graph = build_extraction_graph()
    config = {"configurable": {"thread_id": meeting_id}}
    
    async for event in graph.astream(initial_state, config=config):
        # event contains the node name and updated state
        for node_name, state_update in event.items():
            yield {
                "node": node_name,
                "state": state_update,
                "progress": _calculate_progress(node_name),
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