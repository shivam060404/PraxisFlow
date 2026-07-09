from deepgram import DeepgramClient, PrerecordedOptions, FileSource
from typing import Optional
import asyncio
import logging
import json
from datetime import datetime

from app.core.config import settings
from app.db.prisma import get_prisma
from app.schemas import TranscriptCreate, UtteranceCreate, TranscriptSpan

logger = logging.getLogger(__name__)


class TranscriptResult:
    """Result of transcription with all metadata."""
    def __init__(
        self,
        id: str,
        meeting_id: str,
        tenant_id: str,
        full_text: str,
        language: str,
        word_count: int,
        duration_ms: int,
        utterances: list,
        words: list,
        redaction_applied: bool = False,
    ):
        self.id = id
        self.meeting_id = meeting_id
        self.tenant_id = tenant_id
        self.full_text = full_text
        self.language = language
        self.word_count = word_count
        self.duration_ms = duration_ms
        self.utterances = utterances
        self.words = words
        self.redaction_applied = redaction_applied


class DeepgramASRService:
    """Deepgram Nova-2 ASR service with diarization."""
    
    def __init__(self):
        self.client = DeepgramClient(settings.DEEPGRAM_API_KEY)
        
        self.options = PrerecordedOptions(
            model=settings.DEEPGRAM_MODEL,
            language=settings.DEEPGRAM_LANGUAGE,
            smart_format=settings.DEEPGRAM_PUNCTUATE,
            diarize=settings.DEEPGRAM_DIARIZE,
            utterances=settings.DEEPGRAM_UTTERANCES,
            punctuate=settings.DEEPGRAM_PUNCTUATE,
            paragraphs=settings.DEEPGRAM_PARAGRAPHS,
            filler_words=False,
            keywords=["action item", "decision", "deadline", "follow up", "blocker"],
        )
    
    async def transcribe(
        self,
        audio_url: str,
        meeting_id: str,
        tenant_id: str,
    ) -> TranscriptResult:
        """Transcribe audio from URL."""
        logger.info(f"Starting transcription for meeting {meeting_id}")
        
        try:
            # Call Deepgram API
            response = await self.client.listen.async_prerecorded.v("1").transcribe_url(
                {"url": audio_url},
                self.options,
            )
            
            # Parse response
            transcript = self._parse_response(response, meeting_id, tenant_id)
            
            # Persist to database
            await self._persist_transcript(transcript)
            
            logger.info(f"Transcription completed for meeting {meeting_id}: {transcript.word_count} words")
            
            return transcript
            
        except Exception as e:
            logger.error(f"Transcription failed for meeting {meeting_id}: {e}")
            raise
    
    def _parse_response(
        self,
        response,
        meeting_id: str,
        tenant_id: str,
    ) -> TranscriptResult:
        """Parse Deepgram response into our internal format."""
        import uuid
        
        # Extract data from response
        results = response.results
        channels = results.channels
        
        if not channels:
            raise ValueError("No channels in Deepgram response")
        
        channel = channels[0]
        alternatives = channel.alternatives
        
        if not alternatives:
            raise ValueError("No alternatives in Deepgram response")
        
        transcript_alt = alternatives[0]
        
        # Full text
        full_text = transcript_alt.transcript
        
        # Words with timestamps and speaker info
        words = []
        if hasattr(transcript_alt, 'words') and transcript_alt.words:
            for i, word in enumerate(transcript_alt.words):
                words.append({
                    "index": i,
                    "word": word.word,
                    "start": word.start,
                    "end": word.end,
                    "confidence": word.confidence,
                    "speaker": getattr(word, 'speaker', 0),
                    "speaker_confidence": getattr(word, 'speaker_confidence', 0),
                })
        
        # Utterances (diarized segments)
        utterances = []
        if hasattr(results, 'utterances') and results.utterances:
            for utt in results.utterances:
                utterances.append({
                    "speaker": f"Speaker {utt.speaker}",
                    "text": utt.transcript,
                    "start": utt.start,
                    "end": utt.end,
                    "confidence": utt.confidence,
                    "words": [
                        {"word": w.word, "start": w.start, "end": w.end, "confidence": w.confidence}
                        for w in utt.words
                    ] if hasattr(utt, 'words') and utt.words else [],
                })
        
        # Calculate metadata
        word_count = len(words)
        duration_ms = int(words[-1]["end"] * 1000) if words else 0
        
        return TranscriptResult(
            id=str(uuid.uuid4()),
            meeting_id=meeting_id,
            tenant_id=tenant_id,
            full_text=full_text,
            language=settings.DEEPGRAM_LANGUAGE,
            word_count=word_count,
            duration_ms=duration_ms,
            utterances=utterances,
            words=words,
        )
    
    async def _persist_transcript(self, transcript: TranscriptResult):
        """Save transcript to database."""
        db = await get_prisma()
        
        # Create transcript record
        await db.transcript.create(
            data={
                "id": transcript.id,
                "meetingId": transcript.meeting_id,
                "fullText": transcript.full_text,
                "language": transcript.language,
                "wordCount": transcript.word_count,
                "durationMs": transcript.duration_ms,
                "redactionApplied": transcript.redaction_applied,
            }
        )
        
        # Create utterances
        if transcript.utterances:
            utterance_data = []
            word_idx = 0
            
            for utt in transcript.utterances:
                word_start = word_idx
                word_count = len(utt.get("words", []))
                word_end = word_idx + word_count - 1 if word_count > 0 else word_idx
                
                utterance_data.append({
                    "transcriptId": transcript.id,
                    "speakerLabel": utt["speaker"],
                    "text": utt["text"],
                    "startTimeMs": int(utt["start"] * 1000),
                    "endTimeMs": int(utt["end"] * 1000),
                    "confidence": utt["confidence"],
                    "wordStartIdx": word_start,
                    "wordEndIdx": max(word_start, word_end),
                })
                word_idx += word_count
            
            await db.utterance.create_many(data=utterance_data)
        
        # Update meeting status
        await db.meeting.update(
            where={"id": transcript.meeting_id},
            data={"status": "TRANSCRIBED"},
        )


async def transcribe_meeting(audio_url: str, meeting_id: str, tenant_id: str) -> TranscriptResult:
    """Convenience function to transcribe a meeting."""
    service = DeepgramASRService()
    return await service.transcribe(audio_url, meeting_id, tenant_id)