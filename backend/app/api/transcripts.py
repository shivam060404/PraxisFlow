from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from uuid import UUID

from app.db.prisma import get_db
from app.schemas import Transcript, Utterance, TranscriptChunk, PaginatedResponse

router = APIRouter(prefix="/transcripts", tags=["Transcripts"])


@router.get("/meeting/{meeting_id}", response_model=Transcript)
async def get_transcript_by_meeting(
    meeting_id: UUID,
    db=Depends(get_db),
):
    """Get transcript for a meeting."""
    transcript = await db.transcript.find_unique(
        where={"meetingId": str(meeting_id)},
        include={"utterances": {"orderBy": {"startTimeMs": "asc"}}},
    )
    
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript not found for this meeting",
        )
    
    return transcript


@router.get("/{transcript_id}", response_model=Transcript)
async def get_transcript(
    transcript_id: UUID,
    db=Depends(get_db),
):
    """Get transcript by ID."""
    transcript = await db.transcript.find_unique(
        where={"id": str(transcript_id)},
        include={"utterances": {"orderBy": {"startTimeMs": "asc"}}},
    )
    
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript not found",
        )
    
    return transcript


@router.get("/{transcript_id}/utterances", response_model=List[Utterance])
async def get_utterances(
    transcript_id: UUID,
    start_time_ms: Optional[int] = Query(None, ge=0),
    end_time_ms: Optional[int] = Query(None, ge=0),
    speaker_label: Optional[str] = None,
    db=Depends(get_db),
):
    """Get utterances for a transcript with optional filtering."""
    transcript = await db.transcript.find_unique(where={"id": str(transcript_id)})
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript not found",
        )
    
    where = {"transcriptId": str(transcript_id)}
    if start_time_ms is not None:
        where["endTimeMs"] = {"gte": start_time_ms}
    if end_time_ms is not None:
        where["startTimeMs"] = {"lte": end_time_ms}
    if speaker_label:
        where["speakerLabel"] = speaker_label
    
    utterances = await db.utterance.find_many(
        where=where,
        order={"startTimeMs": "asc"},
    )
    
    return utterances


@router.get("/{transcript_id}/chunks", response_model=List[TranscriptChunk])
async def get_transcript_chunks(
    transcript_id: UUID,
    chunk_size: int = Query(2000, ge=100, le=5000),
    overlap: int = Query(200, ge=0, le=1000),
    db=Depends(get_db),
):
    """Get transcript split into chunks for processing."""
    transcript = await db.transcript.find_unique(
        where={"id": str(transcript_id)},
        include={"utterances": {"orderBy": {"startTimeMs": "asc"}}},
    )
    
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript not found",
        )
    
    # Reconstruct words with indices from utterances
    words = []
    word_idx = 0
    for utterance in transcript.utterances:
        utterance_words = utterance.text.split()
        for word in utterance_words:
            words.append({
                "index": word_idx,
                "text": word,
                "speaker_label": utterance.speaker_label,
                "start_time_ms": utterance.start_time_ms,
                "end_time_ms": utterance.end_time_ms,
                "confidence": utterance.confidence,
            })
            word_idx += 1
    
    # Create chunks
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk_words = words[i:i + chunk_size]
        if not chunk_words:
            break
        
        chunk_text = " ".join(w["text"] for w in chunk_words)
        speakers = list(set(w["speaker_label"] for w in chunk_words))
        
        chunks.append(TranscriptChunk(
            index=len(chunks),
            text=chunk_text,
            word_start=chunk_words[0]["index"],
            word_end=chunk_words[-1]["index"],
            speakers=speakers,
        ))
        
        if i + chunk_size >= len(words):
            break
    
    return chunks


@router.get("/{transcript_id}/span", response_model=dict)
async def get_transcript_span(
    transcript_id: UUID,
    word_start: int = Query(..., ge=0),
    word_end: int = Query(..., ge=0),
    db=Depends(get_db),
):
    """Get transcript text for a specific word span."""
    transcript = await db.transcript.find_unique(
        where={"id": str(transcript_id)},
        include={"utterances": {"orderBy": {"startTimeMs": "asc"}}},
    )
    
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript not found",
        )
    
    # Reconstruct words with indices
    words = []
    word_idx = 0
    for utterance in transcript.utterances:
        utterance_words = utterance.text.split()
        for word in utterance_words:
            words.append({
                "index": word_idx,
                "text": word,
                "speaker_label": utterance.speaker_label,
                "start_time_ms": utterance.start_time_ms,
                "end_time_ms": utterance.end_time_ms,
                "confidence": utterance.confidence,
            })
            word_idx += 1
    
    if word_start >= len(words) or word_end >= len(words) or word_start > word_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid word span",
        )
    
    span_words = words[word_start:word_end + 1]
    text = " ".join(w["text"] for w in span_words)
    speakers = list(set(w["speaker_label"] for w in span_words))
    start_time = min(w["start_time_ms"] for w in span_words)
    end_time = max(w["end_time_ms"] for w in span_words)
    confidence = sum(w["confidence"] or 0 for w in span_words) / len(span_words)
    
    return {
        "text": text,
        "word_start": word_start,
        "word_end": word_end,
        "speakers": speakers,
        "start_time_ms": start_time,
        "end_time_ms": end_time,
        "confidence": confidence,
    }


@router.get("/meeting/{meeting_id}/span", response_model=dict)
async def get_transcript_span_by_meeting(
    meeting_id: UUID,
    word_start: int = Query(..., ge=0),
    word_end: int = Query(..., ge=0),
    db=Depends(get_db),
):
    """Get transcript text for a specific word span by meeting ID."""
    transcript = await db.transcript.find_unique(
        where={"meetingId": str(meeting_id)},
        include={"utterances": {"orderBy": {"startTimeMs": "asc"}}},
    )
    
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript not found for this meeting",
        )
    
    # Reconstruct words with indices
    words = []
    word_idx = 0
    for utterance in transcript.utterances:
        utterance_words = utterance.text.split()
        for word in utterance_words:
            words.append({
                "index": word_idx,
                "text": word,
                "speaker_label": utterance.speaker_label,
                "start_time_ms": utterance.start_time_ms,
                "end_time_ms": utterance.end_time_ms,
                "confidence": utterance.confidence,
            })
            word_idx += 1
    
    if word_start >= len(words) or word_end >= len(words) or word_start > word_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid word span",
        )
    
    span_words = words[word_start:word_end + 1]
    text = " ".join(w["text"] for w in span_words)
    speakers = list(set(w["speaker_label"] for w in span_words))
    start_time = min(w["start_time_ms"] for w in span_words)
    end_time = max(w["end_time_ms"] for w in span_words)
    confidence = sum(w["confidence"] or 0 for w in span_words) / len(span_words)
    
    return {
        "text": text,
        "word_start": word_start,
        "word_end": word_end,
        "speakers": speakers,
        "start_time_ms": start_time,
        "end_time_ms": end_time,
        "confidence": confidence,
    }


@router.get("/{transcript_id}/search")
async def search_transcript(
    transcript_id: UUID,
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    db=Depends(get_db),
):
    """Search transcript for a query string."""
    transcript = await db.transcript.find_unique(
        where={"id": str(transcript_id)},
        include={"utterances": {"orderBy": {"startTimeMs": "asc"}}},
    )
    
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript not found",
        )
    
    # Simple text search (in production, use full-text search or vector search)
    results = []
    query_lower = q.lower()
    
    for utterance in transcript.utterances:
        if query_lower in utterance.text.lower():
            # Find word indices
            words = utterance.text.split()
            for i, word in enumerate(words):
                if query_lower in word.lower():
                    results.append({
                        "utterance_id": utterance.id,
                        "text": utterance.text,
                        "speaker_label": utterance.speaker_label,
                        "start_time_ms": utterance.start_time_ms,
                        "end_time_ms": utterance.end_time_ms,
                        "match_word_index": i,
                        "context": utterance.text[max(0, i-5):i+5],
                    })
                    break
        
        if len(results) >= limit:
            break
    
    return {"query": q, "results": results, "total": len(results)}