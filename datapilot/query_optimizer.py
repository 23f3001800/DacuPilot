"""Session query optimization and query caching for conversational retrieval.

Optimizes user queries across multi-turn sessions by:
1. Stripping conversational filler noise to focus retrieval on high-signal content tokens.
2. Resolving conversational coreferences ("it", "that document", "the previous one") using previous dialogue context.
3. Preventing retrieval contamination when topics switch.
4. Operating dynamically and domain-agnostically so any knowledge package works without code changes.
5. Caching in-session query responses to deliver sub-millisecond repeated lookups.
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
    r"\b(it|that|this|those|they|them|there|these|the same|carry over|for that|for this|"
    r"the previous one|the earlier one|that document|this document|the document|his|her|their|instead|otherwise)\b",
    re.IGNORECASE,
)

# Stop words to ignore when extracting salient context entities
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "had", "has", "have", "he", "her", "him", "his", "how", "i", "in", "is",
    "it", "its", "me", "my", "no", "not", "of", "on", "or", "our", "she",
    "so", "that", "the", "their", "them", "then", "there", "these", "they",
    "this", "to", "was", "we", "were", "what", "when", "where", "which",
    "who", "why", "will", "with", "would", "you", "your",
}

# Dynamic registry for knowledge package topic headings (populated at startup / ingestion)
_REGISTERED_TOPICS: set[str] = set()
_TOPICS_LOCK = threading.Lock()


def register_knowledge_topics(topics: Sequence[str]) -> None:
    """Dynamically register topic names or section titles from the active knowledge base.

    This ensures DocuPilot is 100% domain-agnostic: whether loaded with medical, legal,
    procurement, financial, or engineering documents, topics are learned at runtime.
    """
    with _TOPICS_LOCK:
        for t in topics:
            if t and isinstance(t, str):
                cleaned = t.strip()
                if cleaned:
                    _REGISTERED_TOPICS.add(cleaned)


def get_registered_topics() -> list[str]:
    """Retrieve all dynamically registered knowledge package topics."""
    with _TOPICS_LOCK:
        return sorted(_REGISTERED_TOPICS)


def extract_salient_terms(text: str, max_terms: int = 6) -> list[str]:
    """Extract informative non-stopword tokens or phrases from dialogue turns."""
    words = re.findall(r"[A-Za-z0-9_.-]+", text)
    salient: list[str] = []
    for word in words:
        w_lower = word.lower()
        if len(word) >= 3 and w_lower not in _STOP_WORDS:
            salient.append(word)
    # Deduplicate while preserving sequence order
    return list(dict.fromkeys(salient))[:max_terms]


def is_topic_switch(
    current_question: str,
    previous_question: str,
    active_topic: str = "",
) -> bool:
    """Determine whether the current question introduces a new topic without referencing the prior turn."""
    curr_clean = current_question.strip().lower()
    if not curr_clean or not previous_question:
        return False

    # If it contains coreference pronouns or elliptical triggers, it is a follow-up, NOT a clean topic switch
    if _ELLIPTICAL_PATTERNS.search(curr_clean):
        return False

    # Extract salient content tokens from both questions
    curr_terms = set(w.lower() for w in extract_salient_terms(current_question))
    prev_terms = set(w.lower() for w in extract_salient_terms(previous_question))

    # If questions share no salient content words, and current question is substantial (> 4 words), it's a topic switch
    overlap = curr_terms & prev_terms
    if not overlap and len(curr_clean.split()) >= 4:
        return True

    return False


def optimize_session_query(
    question: str,
    history_messages: Sequence[Any],
    active_topic: str = "",
) -> str:
    """Optimize a user's question for knowledge-base retrieval in a conversational session.

    Performs:
    1. Conversational noise stripping (e.g. "Can you please tell me...").
    2. Conversational coreference resolution ("it", "that document", "the previous one")
       derived dynamically from the previous dialogue turns.
    3. Topic switching defense: when a new topic is detected, previous context is NOT
       carried forward, preventing cross-topic retrieval contamination.
    4. Domain-agnostic topic grounding: uses dynamically extracted topics from the active
       knowledge package rather than hardcoded keywords.
    """
    cleaned = question.strip()
    if not cleaned:
        return cleaned

    # Check if this question refers to previous context via pronouns or brevity
    salient_query_terms = extract_salient_terms(cleaned)
    is_very_short = len(salient_query_terms) <= 2
    has_pronoun = bool(_ELLIPTICAL_PATTERNS.search(cleaned))

    # Strip conversational preambles
    stripped = _CONVERSATIONAL_PREFIXES.sub("", cleaned).strip()
    if not stripped:
        stripped = cleaned

    # Find the most recent human and AI messages from history
    last_human_content = ""
    last_ai_content = ""
    if history_messages:
        for msg in reversed(history_messages):
            content = getattr(msg, "content", "")
            if not isinstance(content, str) or not content:
                continue
            msg_type = getattr(msg, "type", "") or type(msg).__name__
            if ("Human" in msg_type or msg_type == "human") and not last_human_content:
                if content.strip() != question.strip():
                    last_human_content = content.strip()
            elif ("AI" in msg_type or msg_type == "ai") and not last_ai_content:
                last_ai_content = content.strip()
            if last_human_content and last_ai_content:
                break

    # Check for topic switch: if substantive new question without pronouns, do NOT contaminate
    if last_human_content and is_topic_switch(cleaned, last_human_content, active_topic):
        return stripped

    # If it is a standalone specific query (more than 2 content terms without pronouns), return clean query
    if not is_very_short and not has_pronoun:
        return stripped

    # Extract salient context terms from previous human and AI turns
    recent_context_terms: list[str] = []
    if last_human_content:
        human_terms = extract_salient_terms(last_human_content, max_terms=5)
        recent_context_terms.extend(human_terms)

    # Check if AI mentioned a specific document filename (e.g. Proposal Ashok.pdf) or entity
    if last_ai_content:
        doc_matches = re.findall(r"[\w-]+\.(?:pdf|docx|txt|xlsx|csv)", last_ai_content, re.IGNORECASE)
        for doc in doc_matches:
            if doc not in recent_context_terms:
                recent_context_terms.insert(0, doc)

    # Grounding from active topic if present (domain-agnostic: tokenizes active topic itself)
    topic_context_terms: list[str] = []
    if active_topic:
        topic_context_terms = extract_salient_terms(active_topic, max_terms=4)

    # Assemble query components
    additions: list[str] = []
    if recent_context_terms:
        # Deduplicate terms
        additions.append(" ".join(dict.fromkeys(recent_context_terms)))
    elif topic_context_terms:
        additions.append(" ".join(dict.fromkeys(topic_context_terms)))

    if additions:
        return f"{' '.join(additions)} {stripped}".strip()

    return stripped


class SessionQueryCache:
    """Thread-safe LRU cache storing recent (thread_id, query) results."""

    def __init__(self, capacity_per_session: int = 16):
        self._capacity = capacity_per_session
        self._lock = threading.Lock()
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
