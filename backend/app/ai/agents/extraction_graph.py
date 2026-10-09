from langgraph.graph import StateGraph, END
from langgraph.types import Command, interrupt
from langchain_core.messages import SystemMessage, HumanMessage
from typing import List, Optional, Dict, Any
import json
import logging
import asyncio
import time
import hashlib
from datetime import datetime, timedelta
from uuid import uuid4

from app.core.config import settings
from app.ai.agents.schemas import (
    ExtractionState,
    ExtractionResult,
    ExtractedTask,
    TranscriptChunk,
    VerificationResult,
    GroundedVerificationInput,
    JSONRepairAttempt,
    HITLPayload,
)
from app.clients.llm_gateway.client import get_gateway_client, LLMGatewayError, BudgetExceededError
from app.ai.prompts.catalog import (
    DEDUPLICATION_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    JSON_REPAIR_PROMPT,
    VERIFICATION_SYSTEM_PROMPT,
)
from app.ai.rag import RAGService, RAGServiceError
from app.observability.otel import genai_tracer, LLMCallAttributes, trace_llm_call
from app.db.prisma import get_prisma

logger = logging.getLogger(__name__)


# ─── Constants ───
MAX_RETRIES = 3
BASE_RETRY_DELAY = 2.0  # seconds
MAX_RETRY_DELAY = 30.0
JSON_REPAIR_MAX_ATTEMPTS = 3
HITL_CONFIDENCE_THRESHOLD = 0.70
HITL_HALLUCINATION_THRESHOLD = 0.15


# ─── Utility Functions ───

async def _call_gateway_with_retry(
    messages: List[Dict[str, str]],
    pipeline_node: str,
    state: ExtractionState,
    response_format: Optional[Dict] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Any:
    """Call LLM Gateway with exponential backoff retry."""
    gateway = await get_gateway_client()
    last_error = None
    
    for attempt in range(MAX_RETRIES):
        try:
            response = await gateway.chat_completion(
                messages=messages,
                pipeline_node=pipeline_node,
                tenant_id=state.tenant_id,
                user_id=state.user_id,
                meeting_id=state.meeting_id,
                pipeline_run_id=state.pipeline_run_id,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                use_cache=(pipeline_node != "extraction"),  # Don't cache extraction (non-deterministic)
            )
            return response.content
            
        except BudgetExceededError as e:
            logger.error(f"Budget exceeded for {pipeline_node}: {e}")
            raise
            
        except LLMGatewayError as e:
            last_error = e
            delay = min(BASE_RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
            logger.warning(f"{pipeline_node} attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
            await asyncio.sleep(delay)
            
        except Exception as e:
            last_error = e
            delay = min(BASE_RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
            logger.warning(f"{pipeline_node} attempt {attempt + 1} failed with unexpected error: {e}. Retrying in {delay}s...")
            await asyncio.sleep(delay)
    
    raise LLMGatewayError(f"All retries exhausted for {pipeline_node}. Last error: {last_error}")


async def _parse_json_with_repair(
    content: str,
    schema_model: type,
    pipeline_node: str,
    state: ExtractionState,
    context: str = "",
) -> Any:
    """Parse JSON with automatic repair using Pydantic error feedback."""
    repair_attempts = []
    
    for attempt in range(JSON_REPAIR_MAX_ATTEMPTS):
        try:
            # Strip markdown code blocks if present
            cleaned_content = content.strip()
            if cleaned_content.startswith("```"):
                import re
                cleaned_content = re.sub(r"^```(?:json)?\n|\n```$", "", cleaned_content, flags=re.IGNORECASE)
            
            # Try direct parsing first
            data = json.loads(cleaned_content)
            return schema_model.model_validate(data)
            
        except json.JSONDecodeError as e:
            error_msg = f"JSON decode error: {e}"
        except Exception as e:
            error_msg = f"Validation error: {e}"
        
        # Record repair attempt
        repair_attempts.append(JSONRepairAttempt(
            original_output=content,
            error=error_msg,
            attempt_number=attempt + 1,
        ))
        
        if attempt < JSON_REPAIR_MAX_ATTEMPTS - 1:
            # Ask LLM to repair
            schema_json = schema_model.model_json_schema()
            repair_messages = [
                SystemMessage(content=JSON_REPAIR_PROMPT.format(
                    error=error_msg,
                    original_output=content,
                    schema=json.dumps(schema_json, indent=2),
                )),
                HumanMessage(content=f"Context: {context}\n\nFix the JSON output above."),
            ]
            
            try:
                role_map = {"human": "user", "ai": "assistant", "system": "system"}
                repaired_content = await _call_gateway_with_retry(
                    messages=[{"role": role_map.get(m.type, m.type), "content": m.content} for m in repair_messages],
                    pipeline_node=f"{pipeline_node}_repair",
                    state=state,
                    temperature=0.0,
                )
                content = repaired_content
                logger.info(f"JSON repair attempt {attempt + 1} for {pipeline_node}")
            except Exception as e:
                logger.error(f"JSON repair failed for {pipeline_node}: {e}")
                break
    
    # All repair attempts failed
    state.errors.append(f"{pipeline_node}: JSON repair failed after {JSON_REPAIR_MAX_ATTEMPTS} attempts. Last error: {error_msg}")
    state.retry_count[pipeline_node] = state.retry_count.get(pipeline_node, 0) + 1
    raise ValueError(f"Failed to parse/repair JSON for {pipeline_node}: {error_msg}")


def _get_transcript_segment(words: List[str], start_idx: int, end_idx: int) -> str:
    """Get transcript text for a word span."""
    if start_idx >= len(words) or end_idx >= len(words) or start_idx < 0:
        return ""
    end_idx = min(end_idx, len(words) - 1)
    segment_words = words[start_idx:end_idx + 1]
    return " ".join(segment_words)


def _build_full_transcript_context(state: ExtractionState, max_chars: int = 8000) -> str:
    """Build full transcript context for grounded verification."""
    full_text = " ".join(chunk.text for chunk in state.transcript_chunks)
    if len(full_text) > max_chars:
        return full_text[:max_chars] + "... [truncated]"
    return full_text


async def _retrieve_grounding_context(state: ExtractionState, query: str) -> str:
    """Optionally augment verification with indexed, tenant-scoped evidence."""
    if not settings.RAG_ENABLED:
        return ""
    try:
        service = RAGService(await get_gateway_client())
        documents = await service.retrieve(
            query=query,
            tenant_id=state.tenant_id,
            user_id=state.user_id,
            meeting_id=state.meeting_id,
            score_threshold=settings.RAG_SCORE_THRESHOLD,
        )
        return service.format_context(documents, settings.RAG_MAX_CONTEXT_CHARS)
    except RAGServiceError as exc:
        logger.warning("RAG grounding unavailable; using transcript fallback: %s", exc)
        return ""


# ─── LangGraph Nodes with OTel Tracing ───

async def chunking_node(state: ExtractionState) -> ExtractionState:
    """Split transcript into semantic chunks."""
    with genai_tracer.trace_llm_call(LLMCallAttributes(
        system="langgraph",
        model="chunking_algorithm",
        pipeline_node="chunking",
        tenant_id=state.tenant_id,
        user_id=state.user_id,
        meeting_id=state.meeting_id,
        pipeline_run_id=state.pipeline_run_id,
    )):
        try:
            genai_tracer.log_pipeline_step("chunking", "started", meeting_id=state.meeting_id)
            
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
            genai_tracer.log_pipeline_step("chunking", "completed", chunks_created=len(chunks))
            
        except Exception as e:
            logger.error(f"Chunking failed: {e}")
            state.errors.append(f"Chunking failed: {str(e)}")
            genai_tracer.log_pipeline_step("chunking", "failed", error=str(e))
            raise
        
        return state


async def extraction_node(state: ExtractionState) -> ExtractionState:
    """Extract tasks from each transcript chunk with JSON repair and retry."""
    with genai_tracer.trace_llm_call(LLMCallAttributes(
        system="gateway",
        model=settings.EXTRACTION_MODEL,
        pipeline_node="extraction",
        tenant_id=state.tenant_id,
        user_id=state.user_id,
        meeting_id=state.meeting_id,
        pipeline_run_id=state.pipeline_run_id,
        temperature=settings.EXTRACTION_TEMPERATURE,
    )):
        try:
            genai_tracer.log_pipeline_step("extraction", "started", meeting_id=state.meeting_id)
            
            all_tasks = []
            gateway = await get_gateway_client()
            
            for chunk in state.transcript_chunks:
                messages = [
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": f"""Transcript segment (chunk {chunk.index}):
{chunk.text}

Meeting context: {state.meeting_context}

Word indices: {chunk.word_start}-{chunk.word_end}
Speakers: {', '.join(chunk.speakers)}

Extract tasks, decisions, follow-ups, and blockers from this segment."""},
                ]
                
                response_format = {"type": "json_object"}
                
                content = await _call_gateway_with_retry(
                    messages=messages,
                    pipeline_node="extraction",
                    state=state,
                    response_format=response_format,
                    temperature=settings.EXTRACTION_TEMPERATURE,
                )
                
                # Parse with JSON repair
                result = await _parse_json_with_repair(
                    content=content,
                    schema_model=ExtractionResult,
                    pipeline_node="extraction",
                    state=state,
                    context=f"Chunk {chunk.index}",
                )
                
                # Add chunk metadata to each task
                for task in result.tasks:
                    task.transcript_word_start = chunk.word_start
                    task.transcript_word_end = chunk.word_end
                
                all_tasks.extend(result.tasks)
                
                # Collect meeting summary and topics from first chunk
                if chunk.index == 0:
                    state.meeting_summary = result.meeting_summary
                    state.key_topics = result.key_topics
            
            state.proposed_tasks = all_tasks
            logger.info(f"Extracted {len(all_tasks)} proposed tasks for meeting {state.meeting_id}")
            genai_tracer.log_pipeline_step("extraction", "completed", tasks_extracted=len(all_tasks))
            
        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            state.errors.append(f"Extraction failed: {str(e)}")
            genai_tracer.log_pipeline_step("extraction", "failed", error=str(e))
            raise
        
        return state


async def deduplication_node(state: ExtractionState) -> ExtractionState:
    """Deduplicate tasks using LLM with JSON repair."""
    with genai_tracer.trace_llm_call(LLMCallAttributes(
        system="gateway",
        model=settings.EXTRACTION_MODEL,
        pipeline_node="deduplication",
        tenant_id=state.tenant_id,
        user_id=state.user_id,
        meeting_id=state.meeting_id,
        pipeline_run_id=state.pipeline_run_id,
        temperature=0.0,
    )):
        try:
            genai_tracer.log_pipeline_step("deduplication", "started", input_tasks=len(state.proposed_tasks))
            
            if not state.proposed_tasks:
                state.deduplicated_tasks = []
                return state
            
            # Prepare tasks for LLM
            tasks_json = [task.model_dump() for task in state.proposed_tasks]
            
            messages = [
                {"role": "system", "content": DEDUPLICATION_PROMPT},
                {"role": "user", "content": f"Tasks to deduplicate:\n{json.dumps(tasks_json, indent=2)}"},
            ]
            
            response_format = {"type": "json_object"}
            
            content = await _call_gateway_with_retry(
                messages=messages,
                pipeline_node="deduplication",
                state=state,
                response_format=response_format,
                temperature=0.0,
            )
            
            # Parse with JSON repair - expect list of tasks
            try:
                data = json.loads(content)
                if isinstance(data, dict) and "tasks" in data:
                    deduplicated_data = data["tasks"]
                elif isinstance(data, list):
                    deduplicated_data = data
                else:
                    deduplicated_data = data.get("tasks", [])
            except json.JSONDecodeError:
                deduplicated_data = []
            
            # Validate each task
            deduplicated_tasks = []
            for task_data in deduplicated_data:
                try:
                    task = ExtractedTask.model_validate(task_data)
                    deduplicated_tasks.append(task)
                except Exception as e:
                    logger.warning(f"Skipping invalid deduplicated task: {e}")
            
            state.deduplicated_tasks = deduplicated_tasks
            logger.info(f"Deduplicated {len(state.proposed_tasks)} -> {len(deduplicated_tasks)} tasks")
            genai_tracer.log_pipeline_step("deduplication", "completed", output_tasks=len(deduplicated_tasks))
            
        except Exception as e:
            logger.error(f"Deduplication failed: {e}")
            state.errors.append(f"Deduplication failed: {str(e)}")
            # Fallback to simple deduplication
            state.deduplicated_tasks = _simple_deduplicate(state.proposed_tasks)
            genai_tracer.log_pipeline_step("deduplication", "fallback", error=str(e))
        
        return state


def _simple_deduplicate(tasks: List[ExtractedTask]) -> List[ExtractedTask]:
    """Simple fallback deduplication."""
    unique_tasks = []
    for task in tasks:
        is_duplicate = False
        for existing in unique_tasks:
            if _tasks_similar(task, existing):
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
    return unique_tasks


def _tasks_similar(task1: ExtractedTask, task2: ExtractedTask) -> bool:
    """Simple similarity check for deduplication."""
    title1 = task1.title.lower()
    title2 = task2.title.lower()
    words1 = set(title1.split())
    words2 = set(title2.split())
    if not words1 or not words2:
        return False
    intersection = words1 & words2
    union = words1 | words2
    jaccard = len(intersection) / len(union) if union else 0
    return jaccard > 0.6


async def verification_node(state: ExtractionState) -> ExtractionState:
    """Grounded verification: verify each task against actual transcript evidence."""
    with genai_tracer.trace_llm_call(LLMCallAttributes(
        system="gateway",
        model=settings.VERIFICATION_MODEL,
        pipeline_node="verification",
        tenant_id=state.tenant_id,
        user_id=state.user_id,
        meeting_id=state.meeting_id,
        pipeline_run_id=state.pipeline_run_id,
        temperature=settings.VERIFICATION_TEMPERATURE,
    )):
        try:
            genai_tracer.log_pipeline_step("verification", "started", tasks_to_verify=len(state.deduplicated_tasks))
            
            # Get full transcript for grounding
            db = await get_prisma()
            transcript = await db.transcript.find_unique(
                where={"meetingId": state.meeting_id},
                include={"utterances": {"orderBy": {"startTimeMs": "asc"}}},
            )
            
            if not transcript:
                state.errors.append("Transcript not found for verification")
                return state
            
            # Build word array for span lookup
            words = []
            for utt in transcript.utterances:
                words.extend(utt.text.split())
            
            full_transcript_context = _build_full_transcript_context(state)
            
            verified_tasks = []
            hitl_tasks = []  # Tasks needing human review
            
            # First pass: verify all tasks, collect those needing HITL
            for task in state.deduplicated_tasks:
                try:
                    # Get source transcript segment
                    source_text = _get_transcript_segment(
                        words, task.transcript_word_start, task.transcript_word_end
                    )
                    
                    rag_context = await _retrieve_grounding_context(
                        state, f"{task.title}\n{task.description}"
                    )
                    grounded_context = "\n\n".join(
                        part for part in (rag_context, full_transcript_context) if part
                    )
                    # Build grounded verification prompt with full context
                    verification_prompt = f"""You are verifying an extracted task against the ACTUAL transcript.

FULL TRANSCRIPT CONTEXT (for grounding):
{grounded_context}

SOURCE TRANSCRIPT SEGMENT (the specific words cited):
{source_text}

EXTRACTED TASK TO VERIFY:
- Title: {task.title}
- Description: {task.description}
- Task Type: {task.task_type}
- Assignee Hint: {task.assignee_hint or "None"}
- Deadline Hint: {task.deadline_hint or "None"}
- Source Quote Claimed: {task.source_quote}
- Extraction Confidence: {task.confidence}

VERIFICATION INSTRUCTIONS:
1. Does the SOURCE TRANSCRIPT SEGMENT contain the exact SOURCE QUOTE CLAIMED? Quote the exact matching text.
2. Is the TITLE/DESCRIPTION faithful to what was actually said? 
3. Is ANY information HALLUCINATED (not in the transcript)?
4. Was CRITICAL CONTEXT missed (e.g., conditional language, who said it, dependencies)?

Score each 0-1. If hallucination > 0.15 or faithfulness < 0.7, verdict = FAIL.
If scores are borderline, verdict = NEEDS_REVIEW.
You MUST provide the SUPPORTING_QUOTE from the transcript that proves your verdict.

Respond with valid JSON only."""
                    
                    messages = [
                        {"role": "system", "content": VERIFICATION_SYSTEM_PROMPT},
                        {"role": "user", "content": verification_prompt},
                    ]
                    
                    response_format = {"type": "json_object"}
                    
                    content = await _call_gateway_with_retry(
                        messages=messages,
                        pipeline_node="verification",
                        state=state,
                        response_format=response_format,
                        temperature=settings.VERIFICATION_TEMPERATURE,
                    )
                    
                    verdict = await _parse_json_with_repair(
                        content=content,
                        schema_model=VerificationResult,
                        pipeline_node="verification",
                        state=state,
                        context=f"Task: {task.title}",
                    )
                    
                    # Apply verdict
                    task.faithfulness_score = verdict.faithfulness_score
                    task.hallucination_score = verdict.hallucination_score
                    task.completeness_score = verdict.completeness_score
                    task.verification_reasoning = verdict.reasoning
                    
                    if verdict.verdict == "PASS":
                        task.verification_status = "VERIFIED"
                        verified_tasks.append(task)
                    elif verdict.verdict == "NEEDS_REVIEW":
                        task.verification_status = "NEEDS_REVIEW"
                        # Will be added to verified_tasks after HITL
                        hitl_tasks.append((task, verdict, source_text))
                    else:  # FAIL
                        task.verification_status = "FAILED"
                        # Don't add to verified_tasks - drop it
                        logger.info(f"Task rejected by verification: {task.title} (hallucination={verdict.hallucination_score}, faithfulness={verdict.faithfulness_score})")
                    
                    # Check if this task needs HITL (even if PASS but low confidence/high hallucination)
                    needs_hitl = (
                        task.confidence < HITL_CONFIDENCE_THRESHOLD or 
                        (verdict.hallucination_score and verdict.hallucination_score > HITL_HALLUCINATION_THRESHOLD) or
                        verdict.verdict == "NEEDS_REVIEW"
                    )
                    
                    if needs_hitl and task.verification_status != "FAILED":
                        task.requires_human_review = True
                        task.human_review_reason = _build_hitl_reason(task, verdict)
                        # Ensure it's in hitl_tasks
                        if not any(t for t, _, _ in hitl_tasks if t.title == task.title):
                            hitl_tasks.append((task, verdict, source_text))
                    
                except Exception as e:
                    logger.error(f"Verification failed for task {task.title}: {e}")
                    task.verification_status = "NEEDS_REVIEW"
                    task.verification_reasoning = f"Verification error: {str(e)}"
                    task.requires_human_review = True
                    task.human_review_reason = f"Verification system error: {str(e)}"
                    hitl_tasks.append((task, None, ""))
            
            # If there are tasks needing HITL, interrupt the graph
            if hitl_tasks:
                # Create HITL payload with all tasks needing review
                hitl_payloads = []
                for task, verdict, source_text in hitl_tasks:
                    task.review_id = task.review_id or str(uuid4())
                    suggested_action = "APPROVE" if (verdict and verdict.verdict == "NEEDS_REVIEW") else "REJECT"
                    hitl_payload = HITLPayload(
                        meeting_id=state.meeting_id,
                        tenant_id=state.tenant_id,
                        task_id=task.review_id,
                        interrupt_reason=task.human_review_reason,
                        task_data=task.model_dump(),
                        confidence_score=task.confidence,
                        suggested_action=suggested_action,
                        transcript_evidence=source_text,
                        expires_at=datetime.utcnow() + timedelta(hours=24),
                    )
                    hitl_payloads.append(hitl_payload.model_dump())
                
                # Store interrupt info in state for webhook
                state.interrupted = True
                state.interrupt_reason = f"{len(hitl_tasks)} task(s) require human review"
                state.interrupt_node = "verification"
                state.interrupt_payload = {"tasks": hitl_payloads}

                state.pending_review_tasks = [task for task, _, _ in hitl_tasks]
            
            state.verified_tasks = verified_tasks
            logger.info(f"Verified {len(verified_tasks)} tasks for meeting {state.meeting_id}")
            genai_tracer.log_pipeline_step("verification", "completed", 
                verified=len([t for t in verified_tasks if t.verification_status == "VERIFIED"]),
                pending_review=len([t for t in verified_tasks if t.verification_status == "NEEDS_REVIEW"]),
                rejected=len(state.deduplicated_tasks) - len(verified_tasks))
            
        except Exception as e:
            logger.error(f"Verification node failed: {e}")
            state.errors.append(f"Verification failed: {str(e)}")
            genai_tracer.log_pipeline_step("verification", "failed", error=str(e))
            raise

        return state


async def human_review_node(state: ExtractionState) -> ExtractionState:
    """Pause durably for explicit decisions on tasks requiring human review."""
    if not state.pending_review_tasks:
        return state
    if not state.interrupt_payload:
        raise RuntimeError("Pending review tasks have no review payload")

    db = await get_prisma()
    for task in state.pending_review_tasks:
        payload = next(item for item in state.interrupt_payload["tasks"] if item["task_id"] == task.review_id)
        existing = await db.humanreview.find_first(where={"reviewId": task.review_id})
        if not existing:
            await db.humanreview.create(data={
                "tenantId": state.tenant_id,
                "meetingId": state.meeting_id,
                "reviewId": task.review_id,
                "taskData": task.model_dump(),
                "transcriptEvidence": payload["transcript_evidence"],
                "reason": payload["interrupt_reason"],
                "confidence": task.confidence,
                "status": "PENDING",
            })

    feedback = interrupt({"tasks": state.interrupt_payload["tasks"], "meeting_id": state.meeting_id})
    if not isinstance(feedback, dict):
        raise ValueError("HITL resume payload must be an object")
    decisions = {
        item.get("task_id"): item
        for item in feedback.get("tasks", [])
        if isinstance(item, dict)
    }
    expected = {task.review_id for task in state.pending_review_tasks}
    if len(decisions) != len(feedback.get("tasks", [])) or set(decisions) != expected:
        raise ValueError("HITL feedback must include exactly one decision for every pending task")

    state.human_feedback = feedback
    for task in state.pending_review_tasks:
        decision = decisions[task.review_id]
        action = decision.get("action")
        review_record = {
            "review_id": task.review_id,
            "action": action,
            "reviewer_id": feedback.get("reviewer_id", "unknown"),
            "comment": feedback.get("comment"),
            "modifications": decision.get("modifications"),
            "task_data": task.model_dump(),
        }
        if action == "APPROVE":
            task.verification_status = "VERIFIED"
            state.verified_tasks.append(task)
        elif action == "MODIFY":
            changes = decision.get("modifications") or {}
            allowed = {"title", "description", "assignee_hint", "deadline_hint", "priority_hint"}
            if not changes or set(changes) - allowed:
                raise ValueError("HITL modifications contain unsupported fields")
            modified = ExtractedTask.model_validate({**task.model_dump(), **changes})
            modified.verification_status = "VERIFIED"
            state.verified_tasks.append(modified)
            review_record["task_data"] = modified.model_dump()
        elif action != "REJECT":
            raise ValueError(f"Unsupported HITL action: {action}")
        state.human_review_records.append(review_record)

    state.pending_review_tasks = []
    state.interrupted = False
    state.interrupt_reason = None
    state.interrupt_node = None
    return state


def _build_hitl_reason(task: ExtractedTask, verdict: VerificationResult) -> str:
    """Build human-readable reason for HITL interrupt."""
    reasons = []
    if task.confidence < HITL_CONFIDENCE_THRESHOLD:
        reasons.append(f"Low extraction confidence ({task.confidence:.2f} < {HITL_CONFIDENCE_THRESHOLD})")
    if verdict.hallucination_score and verdict.hallucination_score > HITL_HALLUCINATION_THRESHOLD:
        reasons.append(f"Potential hallucination detected ({verdict.hallucination_score:.2f} > {HITL_HALLUCINATION_THRESHOLD})")
    if verdict.verdict == "NEEDS_REVIEW":
        reasons.append("Verification agent flagged for review")
    return "; ".join(reasons)


async def entity_resolution_node(state: ExtractionState) -> ExtractionState:
    """Resolve assignees and deadlines using EntityResolutionAgent."""
    with genai_tracer.trace_llm_call(LLMCallAttributes(
        system="langgraph",
        model="entity_resolution_agent",
        pipeline_node="entity_resolution",
        tenant_id=state.tenant_id,
        user_id=state.user_id,
        meeting_id=state.meeting_id,
        pipeline_run_id=state.pipeline_run_id,
    )):
        try:
            genai_tracer.log_pipeline_step("entity_resolution", "started", tasks=len(state.verified_tasks))
            
            from app.ai.agents.entity_resolution import EntityResolutionAgent
            
            agent = EntityResolutionAgent()
            resolved_tasks = []
            
            try:
                for task in state.verified_tasks:
                    if task.assignee_hint:
                        try:
                            result = await agent.resolve_assignee(
                                assignee_hint=task.assignee_hint,
                                meeting_id=state.meeting_id,
                                tenant_id=state.tenant_id,
                            )
                            if result.assignee_id and result.confidence >= settings.ENTITY_RESOLUTION_MIN_CONFIDENCE:
                                logger.info(
                                    f"Resolved '{task.assignee_hint}' → {result.assignee_name} "
                                    f"(confidence={result.confidence:.2f}, method={result.method})"
                                )
                                # Persist resolution onto the task so it reaches the DB
                                task.assignee_id = str(result.assignee_id)
                                task.assignee_resolved_by = f"{result.method} ({result.confidence:.2f})"
                        except Exception as e:
                            logger.warning(f"Entity resolution failed for '{task.assignee_hint}': {e}")
                    
                    resolved_tasks.append(task)
            finally:
                await agent.close()
            
            state.final_tasks = resolved_tasks
            logger.info(f"Entity resolution completed for {len(resolved_tasks)} tasks in meeting {state.meeting_id}")
            genai_tracer.log_pipeline_step("entity_resolution", "completed", resolved=len(resolved_tasks))
            
        except Exception as e:
            logger.error(f"Entity resolution failed: {e}")
            state.errors.append(f"Entity resolution failed: {str(e)}")
            genai_tracer.log_pipeline_step("entity_resolution", "failed", error=str(e))
            raise
        
        return state


async def persistence_node(state: ExtractionState) -> ExtractionState:
    """Persist final tasks to database."""
    with genai_tracer.trace_llm_call(LLMCallAttributes(
        system="langgraph",
        model="database",
        pipeline_node="persistence",
        tenant_id=state.tenant_id,
        user_id=state.user_id,
        meeting_id=state.meeting_id,
        pipeline_run_id=state.pipeline_run_id,
    )):
        try:
            genai_tracer.log_pipeline_step("persistence", "started", tasks=len(state.final_tasks))
            db = await get_prisma()
            created_count = 0
            async with db.tx() as tx:
                for task in state.final_tasks:
                    normalized_source = " ".join(task.source_quote.casefold().split())
                    fingerprint = hashlib.sha256(
                        f"{task.task_type}\0{' '.join(task.title.casefold().split())}\0{normalized_source}".encode()
                    ).hexdigest()
                    existing = await tx.task.find_first(where={
                        "meetingId": state.meeting_id,
                        "extractionFingerprint": fingerprint,
                    })
                    if existing:
                        continue

                    initial_status = "VERIFIED" if task.verification_status == "VERIFIED" else (
                        "PENDING_REVIEW" if task.verification_status == "NEEDS_REVIEW" else "EXTRACTED"
                    )
                    data = {
                        "tenantId": state.tenant_id,
                        "meetingId": state.meeting_id,
                        "title": task.title,
                        "description": task.description,
                        "taskType": task.task_type,
                        "status": initial_status,
                        "priority": task.priority_hint,
                        "assigneeHint": task.assignee_hint,
                        "assigneeId": task.assignee_id,
                        "assigneeResolvedBy": task.assignee_resolved_by,
                        "deadlineHint": task.deadline_hint,
                        "transcriptWordStart": task.transcript_word_start,
                        "transcriptWordEnd": task.transcript_word_end,
                        "sourceQuote": task.source_quote,
                        "extractionFingerprint": fingerprint,
                        "verificationStatus": task.verification_status,
                        "verificationReasoning": task.verification_reasoning,
                        "extractionConfidence": task.confidence,
                    }
                    created = await tx.task.create(data={key: value for key, value in data.items() if value is not None})
                    created_count += 1

                    review_record = next((record for record in state.human_review_records
                        if record.get("task_data", {}).get("review_id") == task.review_id), None)
                    if review_record:
                        await tx.taskauditlog.create(data={
                            "taskId": created.id,
                            "previousStatus": None,
                            "newStatus": "VERIFIED",
                            "changedBy": review_record.get("reviewer_id") or "unknown",
                            "reason": review_record.get("comment") or "Human review decision: " + review_record["action"],
                            "metadata": {"review_id": review_record["review_id"], "action": review_record["action"]},
                        })

                for record in state.human_review_records:
                    prior = await tx.aiauditlog.find_first(where={"reviewId": record["review_id"]})
                    if not prior:
                        await tx.aiauditlog.create(data={
                            "tenantId": state.tenant_id,
                            "meetingId": state.meeting_id,
                            "reviewId": record["review_id"],
                            "decisionType": "HUMAN_REVIEW_" + record["action"],
                            "model": "human-review",
                            "structuredOutput": record["task_data"],
                            "verificationResult": {
                                "action": record["action"],
                                "reviewer_id": record.get("reviewer_id"),
                                "comment": record.get("comment"),
                            },
                        })
                    await tx.humanreview.update(
                        where={"reviewId": record["review_id"]},
                        data={
                            "status": {"APPROVE": "APPROVED", "REJECT": "REJECTED", "MODIFY": "MODIFIED"}[record["action"]],
                            "reviewerId": record.get("reviewer_id"),
                            "reviewerComment": record.get("comment"),
                            "decisionPayload": {
                                "action": record["action"],
                                "modifications": record.get("modifications"),
                                "comment": record.get("comment"),
                            },
                            "reviewedAt": datetime.utcnow(),
                        },
                    )

                await tx.meeting.update(
                    where={"id": state.meeting_id},
                    data={"status": "EXTRACTED"},
                )
            logger.info("Persisted %s new tasks for meeting %s", created_count, state.meeting_id)
            genai_tracer.log_pipeline_step("persistence", "completed", tasks_persisted=created_count)
            return state
        except Exception as e:
            logger.exception("Persistence failed for meeting %s", state.meeting_id)
            state.errors.append(f"Persistence failed: {e}")
            genai_tracer.log_pipeline_step("persistence", "failed", error=str(e))
            raise


# ─── Build Graph with Interrupt Support ───

# ─── Shared Checkpointer ───
# A process-wide reference to the configured saver. Production initializes a
# Postgres saver during API/worker startup; memory is development-only.

from app.ai.agents.checkpointer import get_shared_checkpointer  # re-export for callers


def build_extraction_graph() -> StateGraph:
    """Build the extraction pipeline graph with HITL interrupt support."""

    workflow = StateGraph(ExtractionState)

    # Add nodes
    workflow.add_node("chunking", chunking_node)
    workflow.add_node("extraction", extraction_node)
    workflow.add_node("deduplication", deduplication_node)
    workflow.add_node("verification", verification_node)
    workflow.add_node("human_review", human_review_node)
    workflow.add_node("entity_resolution", entity_resolution_node)
    workflow.add_node("persistence", persistence_node)

    # Define edges
    workflow.set_entry_point("chunking")

    workflow.add_edge("chunking", "extraction")
    workflow.add_edge("extraction", "deduplication")
    workflow.add_edge("deduplication", "verification")
    workflow.add_edge("verification", "human_review")
    workflow.add_edge("human_review", "entity_resolution")
    workflow.add_edge("entity_resolution", "persistence")
    workflow.add_edge("persistence", END)

    # Compile with the shared persistent saver so all API/worker processes see
    # the same interrupted thread state.
    app = workflow.compile(
        checkpointer=get_shared_checkpointer(),
    )

    return app


# ─── Graph Execution Helpers ───

async def run_extraction_pipeline(
    meeting_id: str,
    tenant_id: str,
    user_id: str,
    meeting_context: str = "",
    transcript_chunks: list = None,
    pipeline_run_id: Optional[str] = None,
) -> ExtractionState:
    """Run the full extraction pipeline for a meeting."""

    # Initialize state
    initial_state = ExtractionState(
        meeting_id=meeting_id,
        tenant_id=tenant_id,
        user_id=user_id,
        meeting_context=meeting_context,
        transcript_chunks=transcript_chunks or [],
        pipeline_run_id=pipeline_run_id or str(uuid4()),
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


async def resume_extraction_pipeline(
    meeting_id: str,
    human_feedback: Dict[str, Any],
) -> ExtractionState:
    """Resume the extraction pipeline after HITL interrupt."""
    
    graph = build_extraction_graph()
    config = {"configurable": {"thread_id": meeting_id}}
    
    checkpoint = await graph.aget_state(config)
    values = checkpoint.values if checkpoint and checkpoint.values else {}
    previous_feedback = values.get("human_feedback")
    if previous_feedback and not values.get("interrupted"):
        if previous_feedback != human_feedback:
            raise ValueError("A different human review decision is already checkpointed")
        # The review was accepted, but a later graph node may have failed. Keep
        # executing from the durable checkpoint instead of applying the same
        # interrupt payload twice.
        final_state = await graph.ainvoke(None, config=config)
    else:
        final_state = await graph.ainvoke(Command(resume=human_feedback), config=config)
    
    logger.info(f"Extraction pipeline resumed for meeting {meeting_id}")
    return final_state


async def get_pipeline_state(meeting_id: str) -> Optional[ExtractionState]:
    """Get current pipeline state for a meeting."""
    graph = build_extraction_graph()
    config = {"configurable": {"thread_id": meeting_id}}
    
    try:
        state = await graph.aget_state(config)
        return ExtractionState.model_validate(state.values) if state and state.values else None
    except Exception as e:
        logger.error(f"Failed to get pipeline state for {meeting_id}: {e}")
        return None
