from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from typing import List, Optional
import json
import logging

from app.core.config import settings
from app.agents.schemas import (
    ExtractionState,
    ExtractionResult,
    ExtractedTask,
    TranscriptChunk,
    VerificationResult,
)

logger = logging.getLogger(__name__)


# ─── Prompts ───

EXTRACTION_SYSTEM_PROMPT = """You are a precise meeting intelligence extraction agent.
Your job is to read a meeting transcript segment and extract ONLY what is explicitly stated.

RULES:
1. Extract tasks, decisions, follow-ups, and blockers.
2. NEVER invent information not present in the transcript.
3. If a deadline is vague ("next week"), extract it as-is. Do NOT guess dates.
4. If an assignee is unclear ("someone should"), note it in assignee_hint as null.
5. Include the VERBATIM source quote for every extraction.
6. Rate your confidence honestly. Low confidence = flag for human review.

Respond ONLY with valid JSON matching the provided schema."""


CHUNKING_PROMPT = """Split the following transcript into semantic chunks of approximately {chunk_size} words with {overlap} words overlap.
Each chunk should be a coherent segment of conversation.

Return a JSON array of chunks with:
- index: chunk number
- text: the chunk text
- word_start: starting word index
- word_end: ending word index
- speakers: list of speaker labels in this chunk

Transcript:
{transcript_text}

Word indices are 0-based. The full transcript has {total_words} words."""


VERIFICATION_SYSTEM_PROMPT = """You are a strict verification agent.
Your job is to judge whether an extracted task FAITHFULLY represents what was said in the transcript.

You must evaluate:
1. FAITHFULNESS: Does the task title/description match the source quote? (0-1)
2. HALLUCINATION: Is any information invented that is NOT in the transcript? (0-1)
3. COMPLETENESS: Did the extraction miss critical context? (0-1)

RULES:
- If hallucination_score > 0.1, REJECT the extraction.
- If faithfulness_score < 0.7, REJECT the extraction.
- Provide a brief reasoning for your judgment.

Respond ONLY with valid JSON."""


DEDUPLICATION_PROMPT = """You are given a list of extracted tasks. Some may be duplicates (same task mentioned multiple times).
Identify and merge duplicates. Two tasks are duplicates if they refer to the same action item, decision, or follow-up.

For each group of duplicates, keep the one with the highest confidence and merge the transcript spans (earliest start, latest end).

Return the deduplicated list of tasks."""


# ─── LLM Setup ───

def get_extraction_llm():
    return ChatGroq(
        model=settings.EXTRACTION_MODEL,
        temperature=settings.EXTRACTION_TEMPERATURE,
        api_key=settings.GROQ_API_KEY,
    ).with_structured_output(ExtractionResult)


def get_verification_llm():
    return ChatGroq(
        model=settings.VERIFICATION_MODEL,
        temperature=settings.VERIFICATION_TEMPERATURE,
        api_key=settings.GROQ_API_KEY,
    ).with_structured_output(VerificationResult)


# ─── LangGraph Nodes ───

async def chunking_node(state: ExtractionState) -> ExtractionState:
    """Split transcript into semantic chunks."""
    # For now, use simple chunking - in production use semantic chunking
    full_text = " ".join(chunk.text for chunk in state.transcript_chunks)
    words = full_text.split()
    total_words = len(words)
    
    chunk_size = settings.CHUNK_SIZE
    overlap = settings.CHUNK_OVERLAP
    
    chunks = []
    for i in range(0, total_words, chunk_size - overlap):
        chunk_words = words[i:i + chunk_size]
        if not chunk_words:
            break
        
        chunk_text = " ".join(chunk_words)
        
        # Find which speakers are in this chunk (approximate)
        speakers = []
        for chunk in state.transcript_chunks:
            if chunk.word_start <= i <= chunk.word_end or chunk.word_start <= i + len(chunk_words) <= chunk.word_end:
                speakers.extend(chunk.speakers)
        speakers = list(set(speakers))
        
        chunks.append(TranscriptChunk(
            index=len(chunks),
            text=chunk_text,
            word_start=i,
            word_end=min(i + len(chunk_words) - 1, total_words - 1),
            speakers=speakers,
        ))
        
        if i + chunk_size >= total_words:
            break
    
    state.transcript_chunks = chunks
    logger.info(f"Created {len(chunks)} chunks for meeting {state.meeting_id}")
    
    return state


async def extraction_node(state: ExtractionState) -> ExtractionState:
    """Extract tasks from each transcript chunk."""
    llm = get_extraction_llm()
    
    all_tasks = []
    
    for chunk in state.transcript_chunks:
        try:
            result: ExtractionResult = await llm.ainvoke([
                SystemMessage(content=EXTRACTION_SYSTEM_PROMPT),
                HumanMessage(content=f"""Transcript segment (chunk {chunk.index}):
{chunk.text}

Meeting context: {state.meeting_context}

Word indices: {chunk.word_start}-{chunk.word_end}
Speakers: {', '.join(chunk.speakers)}

Extract tasks, decisions, follow-ups, and blockers from this segment."""),
            ])
            
            # Add chunk metadata to each task
            for task in result.tasks:
                task.transcript_word_start = chunk.word_start
                task.transcript_word_end = chunk.word_end
            
            all_tasks.extend(result.tasks)
            
            # Collect meeting summary and topics from first chunk
            if chunk.index == 0:
                state.meeting_summary = result.meeting_summary
                state.key_topics = result.key_topics
                
        except Exception as e:
            logger.error(f"Extraction failed for chunk {chunk.index}: {e}")
            state.errors.append(f"Chunk {chunk.index} extraction failed: {str(e)}")
    
    state.proposed_tasks = all_tasks
    logger.info(f"Extracted {len(all_tasks)} proposed tasks for meeting {state.meeting_id}")
    
    return state


async def deduplication_node(state: ExtractionState) -> ExtractionState:
    """Deduplicate tasks using embeddings."""
    if not state.proposed_tasks:
        state.deduplicated_tasks = []
        return state
    
    # Simple deduplication for now - in production use embeddings
    unique_tasks = []
    for task in state.proposed_tasks:
        is_duplicate = False
        for existing in unique_tasks:
            # Simple title similarity check
            if _tasks_similar(task, existing):
                # Merge: keep higher confidence, expand span
                if task.confidence > existing.confidence:
                    idx = unique_tasks.index(existing)
                    unique_tasks[idx] = task
                else:
                    existing.transcript_word_start = min(
                        existing.transcript_word_start, task.transcript_word_start
                    )
                    existing.transcript_word_end = max(
                        existing.transcript_word_end, task.transcript_word_end
                    )
                is_duplicate = True
                break
        
        if not is_duplicate:
            unique_tasks.append(task)
    
    state.deduplicated_tasks = unique_tasks
    logger.info(f"Deduplicated {len(state.proposed_tasks)} -> {len(unique_tasks)} tasks")
    
    return state


async def verification_node(state: ExtractionState) -> ExtractionState:
    """Verify each extracted task against the transcript."""
    llm = get_verification_llm()
    
    verified_tasks = []
    
    # Get full transcript for verification
    from app.db.prisma import get_prisma
    db = await get_prisma()
    transcript = await db.transcript.find_unique(
        where={"meetingId": state.meeting_id},
        include={"utterances": {"orderBy": {"startTimeMs": "asc"}}},
    )
    
    if not transcript:
        state.errors.append("Transcript not found for verification")
        return state
    
    # Reconstruct words for span lookup
    words = []
    for utt in transcript.utterances:
        words.extend(utt.text.split())
    
    for task in state.deduplicated_tasks:
        try:
            # Get source transcript segment
            source_text = _get_transcript_segment(
                words, task.transcript_word_start, task.transcript_word_end
            )
            
            verdict: VerificationResult = await llm.ainvoke([
                SystemMessage(content=VERIFICATION_SYSTEM_PROMPT),
                HumanMessage(content=f"""Source transcript segment:
{source_text}

Extracted task:
- Title: {task.title}
- Description: {task.description}
- Assignee hint: {task.assignee_hint}
- Deadline hint: {task.deadline_hint}
- Source quote: {task.source_quote}

Judge this extraction."""),
            ])
            
            if verdict.verdict == "PASS":
                task.verification_status = "VERIFIED"
                task.verification_reasoning = verdict.reasoning
                verified_tasks.append(task)
            elif verdict.verdict == "NEEDS_REVIEW":
                task.verification_status = "PENDING_REVIEW"
                task.verification_reasoning = verdict.reasoning
                verified_tasks.append(task)
            # FAIL = dropped entirely
            
        except Exception as e:
            logger.error(f"Verification failed for task {task.title}: {e}")
            # On verification failure, flag for review
            task.verification_status = "PENDING_REVIEW"
            task.verification_reasoning = f"Verification error: {str(e)}"
            verified_tasks.append(task)
    
    state.verified_tasks = verified_tasks
    logger.info(f"Verified {len(verified_tasks)} tasks for meeting {state.meeting_id}")
    
    return state


async def entity_resolution_node(state: ExtractionState) -> ExtractionState:
    """Resolve assignees and deadlines."""
    # This will be implemented with the EntityResolutionAgent
    # For now, pass through
    state.final_tasks = state.verified_tasks
    return state


async def persistence_node(state: ExtractionState) -> ExtractionState:
    """Persist final tasks to database."""
    from app.db.prisma import get_prisma
    from app.schemas import TaskCreate, TaskStatus, VerificationStatus
    from uuid import UUID
    
    db = await get_prisma()
    
    created_tasks = []
    
    for task in state.final_tasks:
        # Determine initial status based on verification
        if task.verification_status == "VERIFIED":
            initial_status = TaskStatus.VERIFIED
        elif task.verification_status == "PENDING_REVIEW":
            initial_status = TaskStatus.PENDING_REVIEW
        else:
            initial_status = TaskStatus.EXTRACTED
        
        task_create = TaskCreate(
            tenant_id=UUID(state.tenant_id),
            meeting_id=UUID(state.meeting_id),
            title=task.title,
            description=task.description,
            task_type=task.task_type,
            priority=task.priority_hint,
            assignee_hint=task.assignee_hint,
            deadline_hint=task.deadline_hint,
            transcript_word_start=task.transcript_word_start,
            transcript_word_end=task.transcript_word_end,
            source_quote=task.source_quote,
            verification_status=VerificationStatus(task.verification_status),
            verification_reasoning=task.verification_reasoning,
            extraction_confidence=task.confidence,
            status=initial_status,
        )
        
        created = await db.task.create(data=task_create.model_dump())
        created_tasks.append(created)
    
    # Update meeting status
    await db.meeting.update(
        where={"id": state.meeting_id},
        data={"status": "EXTRACTED"},
    )
    
    logger.info(f"Persisted {len(created_tasks)} tasks for meeting {state.meeting_id}")
    
    return state


# ─── Helper Functions ───

def _tasks_similar(task1: ExtractedTask, task2: ExtractedTask) -> bool:
    """Simple similarity check for deduplication."""
    # Title similarity
    title1 = task1.title.lower()
    title2 = task2.title.lower()
    
    # Check for common words
    words1 = set(title1.split())
    words2 = set(title2.split())
    
    if not words1 or not words2:
        return False
    
    intersection = words1 & words2
    union = words1 | words2
    
    jaccard = len(intersection) / len(union) if union else 0
    
    return jaccard > 0.6


def _get_transcript_segment(words: list, start_idx: int, end_idx: int) -> str:
    """Get transcript text for a word span."""
    if start_idx >= len(words) or end_idx >= len(words):
        return ""
    
    segment_words = words[start_idx:end_idx + 1]
    return " ".join(segment_words)