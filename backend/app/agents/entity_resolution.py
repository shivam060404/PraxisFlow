from neo4j import AsyncGraphDatabase, AsyncDriver
from typing import Optional, List, Dict, Any
import asyncio
import logging
from rapidfuzz import fuzz

from app.core.config import settings
from app.db.prisma import get_prisma
from app.agents.schemas import EntityResolutionResult

logger = logging.getLogger(__name__)


class EntityResolutionAgent:
    """Resolves assignee hints to actual users using Neo4j graph and fuzzy matching."""
    
    def __init__(self):
        self.driver: Optional[AsyncDriver] = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize Neo4j connection."""
        if self._initialized:
            return
        
        self.driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
        
        # Verify connection
        async with self.driver.session() as session:
            await session.run("RETURN 1")
        
        self._initialized = True
        logger.info("EntityResolutionAgent initialized")
    
    async def close(self):
        """Close Neo4j connection."""
        if self.driver:
            await self.driver.close()
            self._initialized = False
    
    async def resolve_assignee(
        self,
        assignee_hint: str,
        meeting_id: str,
        tenant_id: str,
    ) -> EntityResolutionResult:
        """
        Maps "John from marketing" → User(id=uuid, email=john.doe@company.com)
        """
        if not assignee_hint or not assignee_hint.strip():
            return EntityResolutionResult(
                confidence=0.0,
                method="empty_hint",
            )
        
        await self.initialize()
        
        # 1. Get meeting participants (strong prior)
        participants = await self._get_meeting_participants(meeting_id, tenant_id)
        
        # 2. Try exact/fuzzy name match against participants
        participant_match = self._match_against_participants(assignee_hint, participants)
        if participant_match:
            return EntityResolutionResult(
                assignee_id=participant_match["user_id"],
                assignee_name=participant_match["full_name"],
                assignee_email=participant_match["email"],
                confidence=participant_match["confidence"],
                method="participant_match",
            )
        
        # 3. Try embedding similarity against org-wide users
        # (requires vector search - skip for now, use graph traversal)
        
        # 4. Graph traversal: does any candidate have the mentioned role/team?
        role_filter = self._extract_role_hint(assignee_hint)
        if role_filter:
            graph_match = await self._resolve_by_role_graph(
                assignee_hint, role_filter, tenant_id
            )
            if graph_match:
                return graph_match
        
        # 5. Fuzzy match against all tenant users
        db = await get_prisma()
        all_users = await db.user.find_many(
            where={"tenantId": tenant_id},
        )
        
        user_match = self._match_against_users(assignee_hint, all_users)
        if user_match:
            return EntityResolutionResult(
                assignee_id=user_match["user_id"],
                assignee_name=user_match["full_name"],
                assignee_email=user_match["email"],
                confidence=user_match["confidence"],
                method="tenant_fuzzy_match",
            )
        
        return EntityResolutionResult(
            confidence=0.0,
            method="no_match",
        )
    
    async def _get_meeting_participants(
        self,
        meeting_id: str,
        tenant_id: str,
    ) -> List[Dict[str, Any]]:
        """Get meeting attendees from database."""
        db = await get_prisma()
        
        attendees = await db.attendee.find_many(
            where={"meetingId": meeting_id},
            include={"user": True},
        )
        
        participants = []
        for att in attendees:
            participants.append({
                "user_id": att.userId,
                "email": att.email,
                "full_name": att.displayName,
                "speaker_label": att.speakerLabel,
            })
        
        return participants
    
    def _match_against_participants(
        self,
        hint: str,
        participants: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Fuzzy match assignee hint against meeting participants."""
        hint_lower = hint.lower().strip()
        
        best_match = None
        best_score = 0
        
        for p in participants:
            if not p.get("full_name"):
                continue
            
            name = p["full_name"].lower()
            name_parts = name.split()
            
            # Try different matching strategies
            scores = [
                fuzz.ratio(hint_lower, name),
                fuzz.partial_ratio(hint_lower, name),
                fuzz.token_set_ratio(hint_lower, name),
            ]
            
            # Also check individual name parts
            for part in name_parts:
                scores.append(fuzz.ratio(hint_lower, part))
                scores.append(fuzz.partial_ratio(hint_lower, part))
            
            max_score = max(scores)
            
            if max_score > best_score and max_score >= settings.NAME_MATCH_THRESHOLD:
                best_score = max_score
                best_match = p
        
        if best_match:
            return {
                "user_id": best_match["user_id"],
                "full_name": best_match["full_name"],
                "email": best_match["email"],
                "confidence": best_score / 100.0,
            }
        
        return None
    
    def _match_against_users(
        self,
        hint: str,
        users: List[Any],
    ) -> Optional[Dict[str, Any]]:
        """Fuzzy match against all tenant users."""
        hint_lower = hint.lower().strip()
        
        best_match = None
        best_score = 0
        
        for user in users:
            if not user.fullName:
                continue
            
            name = user.fullName.lower()
            name_parts = name.split()
            
            scores = [
                fuzz.ratio(hint_lower, name),
                fuzz.partial_ratio(hint_lower, name),
                fuzz.token_set_ratio(hint_lower, name),
            ]
            
            for part in name_parts:
                scores.append(fuzz.ratio(hint_lower, part))
                scores.append(fuzz.partial_ratio(hint_lower, part))
            
            max_score = max(scores)
            
            if max_score > best_score and max_score >= settings.NAME_MATCH_THRESHOLD:
                best_score = max_score
                best_match = user
        
        if best_match:
            return {
                "user_id": best_match.id,
                "full_name": best_match.fullName,
                "email": best_match.email,
                "confidence": best_score / 100.0,
            }
        
        return None
    
    def _extract_role_hint(self, hint: str) -> Optional[str]:
        """Extract role/team hint from assignee string.
        e.g., "John from marketing" -> "marketing"
        """
        import re
        
        # Pattern: "X from Y" or "X in Y" or "X of Y"
        patterns = [
            r"\bfrom\s+(\w+)",
            r"\bin\s+(\w+)",
            r"\bof\s+(\w+)",
            r"\bteam\s+(\w+)",
            r"\bdepartment\s+(\w+)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, hint, re.IGNORECASE)
            if match:
                return match.group(1).lower()
        
        return None
    
    async def _resolve_by_role_graph(
        self,
        hint: str,
        role_filter: str,
        tenant_id: str,
    ) -> Optional[EntityResolutionResult]:
        """Use Neo4j to find users with matching role/team."""
        if not self.driver:
            return None
        
        try:
            async with self.driver.session() as session:
                # Find users in the specified team/department who are in this tenant
                query = """
                MATCH (u:User {tenantId: $tenant_id})-[:MEMBER_OF]->(t:Team)
                WHERE toLower(t.name) CONTAINS $role_filter
                RETURN u.id, u.fullName, u.email, t.name as team
                LIMIT 10
                """
                
                result = await session.run(
                    query,
                    tenant_id=tenant_id,
                    role_filter=role_filter,
                )
                
                candidates = []
                async for record in result:
                    candidates.append({
                        "user_id": record["u.id"],
                        "full_name": record["u.fullName"],
                        "email": record["u.email"],
                        "team": record["team"],
                    })
                
                if candidates:
                    # Try to fuzzy match the name part against candidates
                    name_part = hint.split(" from ")[0].split(" in ")[0].split(" of ")[0].strip()
                    match = self._match_against_users(name_part, candidates)
                    
                    if match:
                        return EntityResolutionResult(
                            assignee_id=match["user_id"],
                            assignee_name=match["full_name"],
                            assignee_email=match["email"],
                            confidence=match["confidence"] * 0.9,  # Slightly lower due to indirection
                            method="graph_role_match",
                        )
        
        except Exception as e:
            logger.error(f"Graph resolution failed: {e}")
        
        return None
    
    async def resolve_deadline(
        self,
        deadline_hint: str,
        meeting_date: str,
    ) -> Optional[str]:
        """Parse deadline hint into ISO date.
        e.g., "by Friday" -> 2024-01-12 (if meeting was 2024-01-08)
        """
        if not deadline_hint or not deadline_hint.strip():
            return None
        
        from dateutil import parser as date_parser
        from dateutil.relativedelta import relativedelta, MO, TU, WE, TH, FR, SA, SU
        from datetime import datetime, timedelta
        import re
        
        try:
            # Parse the meeting date as the reference point
            try:
                ref_date = date_parser.parse(meeting_date)
            except (ValueError, TypeError):
                ref_date = datetime.utcnow()
            
            hint = deadline_hint.lower().strip()
            
            # Map day names to dateutil weekday constants
            day_map = {
                "monday": MO, "tuesday": TU, "wednesday": WE,
                "thursday": TH, "friday": FR, "saturday": SA, "sunday": SU,
                "mon": MO, "tue": TU, "wed": WE, "thu": TH, "fri": FR, "sat": SA, "sun": SU,
            }
            
            # Pattern: "by Friday", "next Friday", "this Friday"
            for day_name, day_const in day_map.items():
                if day_name in hint:
                    # Find the next occurrence of that weekday
                    target = ref_date + relativedelta(weekday=day_const(+1))
                    # If it's the same day, push to next week
                    if target.date() == ref_date.date():
                        target = ref_date + relativedelta(weekday=day_const(+2))
                    return target.date().isoformat()
            
            # Pattern: "next week"
            if "next week" in hint:
                target = ref_date + relativedelta(weeks=+1, weekday=FR)
                return target.date().isoformat()
            
            # Pattern: "end of week"
            if "end of week" in hint or "eow" in hint:
                target = ref_date + relativedelta(weekday=FR(+1))
                return target.date().isoformat()
            
            # Pattern: "end of month", "eom"
            if "end of month" in hint or "eom" in hint:
                target = ref_date + relativedelta(months=+1, day=1) - timedelta(days=1)
                return target.date().isoformat()
            
            # Pattern: "end of quarter", "eoq", "end of Q1/Q2/Q3/Q4"
            if "end of quarter" in hint or "eoq" in hint or re.search(r"end of q\d", hint):
                month = ref_date.month
                quarter_end_month = ((month - 1) // 3 + 1) * 3
                target = ref_date.replace(month=quarter_end_month) + relativedelta(months=+1, day=1) - timedelta(days=1)
                if target.date() <= ref_date.date():
                    target = target + relativedelta(months=+3)
                return target.date().isoformat()
            
            # Pattern: "in X days/weeks"
            match = re.search(r"in\s+(\d+)\s+(day|week|month)s?", hint)
            if match:
                amount = int(match.group(1))
                unit = match.group(2)
                if unit == "day":
                    target = ref_date + timedelta(days=amount)
                elif unit == "week":
                    target = ref_date + timedelta(weeks=amount)
                elif unit == "month":
                    target = ref_date + relativedelta(months=+amount)
                return target.date().isoformat()
            
            # Pattern: "tomorrow"
            if "tomorrow" in hint:
                return (ref_date + timedelta(days=1)).date().isoformat()
            
            # Pattern: "today"
            if "today" in hint:
                return ref_date.date().isoformat()
            
            # Fallback: try to parse as an absolute date
            try:
                parsed = date_parser.parse(hint, fuzzy=True)
                return parsed.date().isoformat()
            except (ValueError, OverflowError):
                pass
            
        except Exception as e:
            logger.warning(f"Failed to resolve deadline '{deadline_hint}': {e}")
        
        return None


# Global instance
entity_resolution_agent = EntityResolutionAgent()