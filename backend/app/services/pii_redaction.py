from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig
from typing import List, Dict, Any, Optional
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class PIIRedactionService:
    """PII redaction using Microsoft Presidio."""
    
    def __init__(self):
        self.analyzer = AnalyzerEngine()
        self.anonymizer = AnonymizerEngine()
        
        # Entities to redact
        self.entities = [
            "PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", 
            "CREDIT_CARD", "US_SSN", "US_BANK_NUMBER",
            "US_PASSPORT", "LOCATION", "DATE_TIME",
            "IP_ADDRESS", "URL", "CRYPTO", "IBAN_CODE",
        ]
        
        # Custom operators for different entity types
        self.operators = {
            "DEFAULT": OperatorConfig("replace", {"new_value": "[REDACTED]"}),
            "PERSON": OperatorConfig("replace", {"new_value": "[PERSON]"}),
            "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "[EMAIL]"}),
            "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "[PHONE]"}),
            "US_SSN": OperatorConfig("replace", {"new_value": "[SSN]"}),
            "CREDIT_CARD": OperatorConfig("replace", {"new_value": "[CREDIT_CARD]"}),
            "LOCATION": OperatorConfig("replace", {"new_value": "[LOCATION]"}),
            "DATE_TIME": OperatorConfig("replace", {"new_value": "[DATE]"}),
        }
    
    def redact_text(self, text: str) -> Dict[str, Any]:
        """
        Redact PII from text.
        Returns dict with: text, has_redactions, redaction_map
        """
        if not text or not text.strip():
            return {
                "text": text,
                "has_redactions": False,
                "redaction_map": [],
            }
        
        # Analyze text for PII
        results = self.analyzer.analyze(
            text=text,
            language="en",
            entities=self.entities,
        )
        
        if not results:
            return {
                "text": text,
                "has_redactions": False,
                "redaction_map": [],
            }
        
        # Anonymize
        anonymized = self.anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators=self.operators,
        )
        
        # Build redaction map
        redaction_map = []
        for result in results:
            redaction_map.append({
                "start": result.start,
                "end": result.end,
                "type": result.entity_type,
                "score": result.score,
                "original_text": text[result.start:result.end],
            })
        
        return {
            "text": anonymized.text,
            "has_redactions": True,
            "redaction_map": redaction_map,
        }
    
    def redact_utterances(self, utterances: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Redact PII from a list of utterances."""
        redacted_utterances = []
        
        for utterance in utterances:
            text = utterance.get("text", "")
            if not text:
                redacted_utterances.append(utterance)
                continue
            
            result = self.redact_text(text)
            
            redacted_utterance = utterance.copy()
            redacted_utterance["text"] = result["text"]
            redacted_utterance["has_redactions"] = result["has_redactions"]
            redacted_utterance["redaction_map"] = result["redaction_map"]
            
            redacted_utterances.append(redacted_utterance)
        
        return redacted_utterances
    
    def is_redaction_needed(self, text: str) -> bool:
        """Quick check if text contains PII."""
        if not text or not text.strip():
            return False
        
        results = self.analyzer.analyze(
            text=text,
            language="en",
            entities=self.entities,
        )
        
        return len(results) > 0


# Global instance
pii_redaction_service = PIIRedactionService()


# Convenience functions
def redact_text(text: str) -> Dict[str, Any]:
    """Redact PII from text."""
    return pii_redaction_service.redact_text(text)


def redact_utterances(utterances: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Redact PII from utterances."""
    return pii_redaction_service.redact_utterances(utterances)