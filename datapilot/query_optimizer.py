"""Session query optimization and query caching for conversational retrieval.

Optimizes user queries across multi-turn sessions by:
1. Stripping conversational filler noise to focus retrieval on high-signal content tokens.
2. Resolving conversational coreferences and elliptical follow-ups using previous dialogue context.
3. Caching identical in-session query responses to deliver sub-millisecond repeated lookups.
"""


import collections


import re
import threading
from typing import Any, Optional, Sequence

# Filler conversational prefixes that dilute keyword matching
_CONVERSATIONAL_PREFIXES = re.compile(
    r"^(?:(?:could|can|would)\s+you\s+(?:please\s+)?(?:tell|explain|clarify|show)\s+(?:me\s+)?|"
    r"i\s+(?:want|would\s+like|need)\s+to\s+(?:know|understand)\s+(?:if|about|whether)\s+|"
    r"please\s+(?:tell|explain|show)\s+(?:me\s+)?|"
    r"hey\s+(?:assistant|datapilot|docupilot)[,\s]+|"
    r"what\s+about\s+|"
    r"how\s+about\s+)",
    re.IGNORECASE,
)

# Pronouns or connective terms signaling reference to previous turn
_ELLIPTICAL_PATTERNS = re.compile(
    r"\b(it|that|this|those|they|them|there|these|the same|carry over|for that|for this|instead|otherwise)\b",
    re.IGNORECASE,
)

_CORE_TOPIC_KEYWORDS = {
    "leave": "annual leave holiday vacation",
    "holiday": "public holidays calendar leave",
    "pricing": "HarvestLink Grove Canopy product pricing subscription",
    "expense": "travel meals reimbursement Petal expense report",
    "security": "ISO 27001 SOC 2 password MFA encryption infosec",
    "excel": "inventory workbook spreadsheet column row pandas",
    "identity": "Aadhaar PAN driving licence passport KYC identity",
    "insurance": "insurance policy NACH mandate FATCA proposal moral hazard benefit illustration",
}


def optimize_session_query(
    question: str,
    history_messages: Sequence[Any],
    active_topic: str = "",
) -> str:
    """Optimize a user's question for knowledge-base retrieval in a conversational session.

    Performs:
    1. Conversational noise stripping
    2. Context carry-forward for follow-up / elliptical questions
    3. Topic grounding
    """
    cleaned = question.strip()
    if not cleaned:
        return cleaned

    # Check if this question refers to previous context
    is_short = len(cleaned.split()) <= 8
    has_pronoun = bool(_ELLIPTICAL_PATTERNS.search(cleaned))

    # Strip conversational preambles
    stripped = _CONVERSATIONAL_PREFIXES.sub("", cleaned).strip()
    if not stripped:
        stripped = cleaned

    # If it is a standalone specific query (> 8 words without pronouns), return cleaned
    if not is_short and not has_pronoun:
        return stripped

    # Extract keywords from recent human messages
    recent_context_terms: list[str] = []
    if history_messages:
        # Look at the most recent prior human messages
        for msg in reversed(history_messages):
            # Check content attribute
            content = getattr(msg, "content", "")
            if not isinstance(content, str) or not content:
                continue
            if getattr(msg, "type", "") == "human" or type(msg).__name__ == "HumanMessage":
                if content.strip() != question.strip():
                    # Extract significant words from previous question
                    words = [w for w in re.findall(r"[A-Za-z0-9]+", content) if len(w) > 3]
                    recent_context_terms.extend(words[:6])
                    break

    # If topic keywords are available, add matching domain context
    topic_context = ""
    if active_topic:
        topic_lower = active_topic.lower()
        for key, domain_terms in _CORE_TOPIC_KEYWORDS.items():
            if key in topic_lower:
                topic_context = domain_terms
                break

    # Construct the optimized query
    context_prefix = " ".join(dict.fromkeys(recent_context_terms))  # deduplicate preserving order
    additions = []
    if context_prefix:
        additions.append(context_prefix)
    elif topic_context:
        additions.append(topic_context)

    if additions:
        return f"{' '.join(additions)} {stripped}".strip()

    return stripped


class SessionQueryCache:
    """Thread-safe LRU cache storing recent (thread_id, query) results."""

    def __init__(self, capacity_per_session: int = 16):
        self._capacity = capacity_per_session
        self._lock = threading.Lock()
        # Maps session_id -> OrderedDict of (normalized_query -> result_dict)
        self._cache: dict[str, collections.OrderedDict] = collections.defaultdict(collections.OrderedDict)

    def get(self, session_id: str, query: str) -> Optional[dict[str, Any]]:
        """Retrieve cached result if present."""
        if not session_id or not query:
            return None
        norm_query = query.strip().lower()
        with self._lock:
            session_entries = self._cache.get(session_id)
            if not session_entries:
                return None
            if norm_query in session_entries:
                session_entries.move_to_end(norm_query)
                return dict(session_entries[norm_query])
        return None

    def put(self, session_id: str, query: str, result: dict[str, Any]) -> None:
        """Store result in cache."""
        if not session_id or not query:
            return
        norm_query = query.strip().lower()
        with self._lock:
            session_entries = self._cache[session_id]
            session_entries[norm_query] = result
            session_entries.move_to_end(norm_query)
            if len(session_entries) > self._capacity:
                session_entries.popitem(last=False)

    def clear_session(self, session_id: str) -> None:
        """Invalidate all cache entries for a given session."""
        with self._lock:
            self._cache.pop(session_id, None)


# Global shared session query cache
GLOBAL_QUERY_CACHE = SessionQueryCache()
