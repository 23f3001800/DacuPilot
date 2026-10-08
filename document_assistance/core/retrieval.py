import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Sequence
from uuid import uuid4

from .loader import KnowledgeSection, split_text

SourceType = Literal["application_kb", "user_document"]
KnowledgeScope = Literal["application", "user", "mixed"]

STOP_WORDS = {
    "a", "about", "am", "an", "and", "are", "as", "at", "be", "been",
    "but", "by", "can", "do", "does", "for", "from", "how", "i", "in",
    "is", "it", "me", "my", "of", "on", "or", "our", "please", "should",
    "tell", "that", "the", "their", "this", "to", "was", "what", "when",
    "where", "which", "who", "why", "with", "would", "you", "your",
}
USER_REFERENCE_TERMS = {
    "uploaded", "upload", "file", "pdf", "page", "pages", "says", "states",
    "shows", "policyholder",
}
POLICY_COMPARISON_TERMS = {
    "against", "compare", "complies", "compliance", "eligible", "meets",
    "pass", "passes", "requirement", "requirements", "satisfy", "satisfies",
    "verified", "validate", "validation", "approved",
}


@dataclass(frozen=True)
class Evidence:
    source_id: str
    source: str
    source_type: SourceType
    authority: str
    section: str
    text: str
    document_id: str = ""
    session_id: str = ""

    @property
    def citation(self) -> str:
        return f"{self.source} — {self.section}"


@dataclass(frozen=True)
class RankedEvidence:
    evidence: Evidence
    score: float


def _tokens(text: str) -> list[str]:
    tokens = []
    for token in re.findall(r"[a-z0-9]+", text.casefold()):
        if len(token) <= 1 or token in STOP_WORDS:
            continue
        if token.endswith("ification"):
            token = token[:-9] + "ify"
        elif token.endswith("uation"):
            token = token[:-6] + "uate"
        elif token.endswith("ation"):
            token = token[:-5] + "e"
        elif token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("ied") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("s") and len(token) > 3:
            token = token[:-1]
        tokens.append(token)
    return tokens


def _chunks_from_sections(
    sections: Iterable[KnowledgeSection],
    source_type: SourceType,
    authority: str,
    session_id: str = "",
    document_id: str = "",
) -> list[Evidence]:
    evidence = []
    for section in sections:
        for index, text in enumerate(split_text(section.text)):
            evidence.append(
                Evidence(
                    source_id=f"{document_id or section.source}:{section.section}:{index}",
                    source=section.source,
                    source_type=source_type,
                    authority=authority,
                    section=section.section,
                    text=text,
                    document_id=document_id,
                    session_id=session_id,
                )
            )
    return evidence


class SessionDocumentStore:
    """In-memory user evidence isolated by opaque conversation thread ID."""

    def __init__(self) -> None:
        self._documents: dict[str, list[Evidence]] = {}
        self._lock = threading.RLock()

    def add_document(
        self,
        session_id: str,
        filename: str,
        pages: Sequence[tuple[str, str]],
    ) -> dict[str, int | str]:
        return self.add_documents(session_id, [(filename, pages)])[0]

    def add_documents(
        self,
        session_id: str,
        documents: Sequence[tuple[str, Sequence[tuple[str, str]]]],
    ) -> list[dict[str, int | str]]:
        additions: list[Evidence] = []
        results: list[dict[str, int | str]] = []
        for filename, pages in documents:
            document_id = uuid4().hex
            sections = [
                KnowledgeSection(source=Path(filename).name, section=label, text=text)
                for label, text in pages
            ]
            chunks = _chunks_from_sections(
                sections,
                source_type="user_document",
                authority="user_provided_evidence",
                session_id=session_id,
                document_id=document_id,
            )
            if not chunks:
                raise ValueError(
                    f"{Path(filename).name}: no readable text was found."
                )
            additions.extend(chunks)
            results.append(
                {"document_id": document_id, "chunk_count": len(chunks)}
            )
        with self._lock:
            self._documents.setdefault(session_id, []).extend(additions)
        return results

    def get_session_evidence(self, session_id: str) -> list[Evidence]:
        with self._lock:
            return list(self._documents.get(session_id, ()))

    def clear_session(self, session_id: str) -> int:
        with self._lock:
            return len(self._documents.pop(session_id, ()))


def route_query(question: str) -> KnowledgeScope:
    """Choose sources before retrieval; uploaded evidence never selects policy."""
    tokens = set(_tokens(question))
    normalized = question.casefold()
    refers_to_user_document = bool(tokens & USER_REFERENCE_TERMS) or any(
        phrase in normalized
        for phrase in (
            "this document",
            "my document",
            "the document",
            "these documents",
            "these pages",
            "the uploaded",
            "this file",
            "my file",
        )
    )
    asks_for_policy_comparison = bool(tokens & POLICY_COMPARISON_TERMS) or any(
        phrase in normalized
        for phrase in ("against our rules", "according to policy", "is it verified")
    )
    if refers_to_user_document and asks_for_policy_comparison:
        return "mixed"
    if refers_to_user_document:
        return "user"
    return "application"


def retrieve_evidence(
    question: str,
    application_sections: Sequence[KnowledgeSection],
    session_id: str,
    user_store: SessionDocumentStore,
    limit: int = 5,
) -> tuple[KnowledgeScope, list[RankedEvidence]]:
    scope = route_query(question)
    candidates: list[Evidence] = []
    if scope in {"application", "mixed"}:
        candidates.extend(
            _chunks_from_sections(
                application_sections,
                source_type="application_kb",
                authority="authoritative_application_knowledge",
            )
        )
    if scope in {"user", "mixed"}:
        candidates.extend(user_store.get_session_evidence(session_id))

    query_tokens = set(_tokens(question))
    if not query_tokens or not candidates:
        return scope, []

    document_frequency: dict[str, int] = {}
    tokenized = []
    for item in candidates:
        terms = _tokens(item.text)
        term_set = set(terms)
        tokenized.append((item, terms, term_set))
        for term in term_set:
            document_frequency[term] = document_frequency.get(term, 0) + 1

    scored: list[RankedEvidence] = []
    for item, terms, term_set in tokenized:
        overlap = query_tokens & term_set
        if not overlap:
            continue
        if len(overlap) / len(query_tokens) < 0.15:
            continue
        tf = {term: terms.count(term) for term in overlap}
        score = sum(
            (1 + math.log(1 + count))
            * math.log(1 + (len(candidates) - document_frequency[term] + 0.5)
                       / (document_frequency[term] + 0.5))
            for term, count in tf.items()
        )
        score += len(overlap) / len(query_tokens)
        scored.append(RankedEvidence(item, score))

    scored.sort(
        key=lambda result: (
            result.score,
            result.evidence.source_type == "application_kb",
        ),
        reverse=True,
    )
    return scope, scored[:limit]
