import collections
import logging
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Optional, Sequence
from uuid import uuid4

from .loader import KnowledgeSection, split_text

logger = logging.getLogger("datapilot.retrieval")

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
    "shows", "policyholder", "proposer", "applicant", "proposal", "mandate",
    "illustration", "nach", "fatca", "document", "documents",
}
POLICY_COMPARISON_TERMS = {
    "against", "compare", "complies", "compliance", "eligible", "meets",
    "pass", "passes", "requirement", "requirements", "satisfy", "satisfies",
    "verified", "validate", "validation", "approved",
}

RRF_K = 60


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
    page: str = ""
    chunk_id: str = ""

    @property
    def citation(self) -> str:
        return f"{self.source} — {self.section}"


@dataclass(frozen=True)
class RankedEvidence:
    evidence: Evidence
    score: float
    bm25_score: float = 0.0
    similarity_score: float = 0.0
    vector_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: float = 0.0


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
        page = getattr(section, "page", "")
        for index, text in enumerate(split_text(section.text)):
            chunk_id = f"{document_id or section.source}:{section.section}:{index}"
            evidence.append(
                Evidence(
                    source_id=chunk_id,
                    source=section.source,
                    source_type=source_type,
                    authority=authority,
                    section=section.section,
                    text=text,
                    document_id=document_id,
                    session_id=session_id,
                    page=page,
                    chunk_id=chunk_id,
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
        CHROMA_STORE.clear_session(session_id)
        with self._lock:
            return len(self._documents.pop(session_id, ()))


class ChromaEvidenceStore:
    """ChromaDB semantic vector index storing Chunk IDs, Vectors, and Document Metadata."""

    def __init__(self) -> None:
        self._collection = None
        self._indexed_ids: set[str] = set()
        self._lock = threading.RLock()

    def _get_collection(self):
        if self._collection is not None:
            return self._collection
        with self._lock:
            if self._collection is None:
                try:
                    import chromadb
                    from chromadb.config import Settings
                    client = chromadb.Client(Settings(anonymized_telemetry=False, is_persistent=False))
                    self._collection = client.get_or_create_collection(
                        name="docupilot_knowledge_base",
                        metadata={"hnsw:space": "cosine"},
                    )
                except Exception as err:
                    logger.debug("ChromaDB initialization error: %s", err)
                    self._collection = None
            return self._collection

    def index(self, items: Sequence[Evidence]) -> None:
        coll = self._get_collection()
        if coll is None or not items:
            return
        with self._lock:
            to_add = [c for c in items if c.source_id not in self._indexed_ids]
            if not to_add:
                return
            ids = [c.source_id for c in to_add]
            docs = [f"{c.source} {c.section}\n{c.text}" for c in to_add]
            metadatas = [
                {
                    "source": c.source,
                    "section": c.section,
                    "page": getattr(c, "page", ""),
                    "chunk_id": c.chunk_id or c.source_id,
                    "source_type": c.source_type,
                    "authority": c.authority,
                    "session_id": c.session_id,
                }
                for c in to_add
            ]
            try:
                coll.add(ids=ids, documents=docs, metadatas=metadatas)
                self._indexed_ids.update(ids)
            except Exception as e:
                logger.debug("Failed adding to ChromaDB: %s", e)

    def query(self, query: str, limit: int = 15, where: Optional[dict] = None) -> dict[str, float]:
        coll = self._get_collection()
        if coll is None or not self._indexed_ids:
            return {}
        try:
            kwargs: dict[str, Any] = {"query_texts": [query], "n_results": min(limit, len(self._indexed_ids))}
            if where:
                kwargs["where"] = where
            results = coll.query(**kwargs)
            scores = {}
            if results and results.get("ids") and results["ids"][0]:
                for chunk_id, dist in zip(results["ids"][0], results["distances"][0]):
                    sim = max(0.0, 1.0 - float(dist) / 2.0)
                    scores[chunk_id] = sim
            return scores
        except Exception as e:
            logger.debug("ChromaDB query error: %s", e)
            return {}

    def clear_session(self, session_id: str) -> None:
        coll = self._get_collection()
        if coll is None or not session_id:
            return
        with self._lock:
            try:
                coll.delete(where={"session_id": session_id})
                self._indexed_ids = {i for i in self._indexed_ids if not i.startswith(session_id)}
            except Exception as e:
                logger.debug("ChromaDB delete session error: %s", e)


CHROMA_STORE = ChromaEvidenceStore()


def route_query(
    question: str,
    user_store: Optional[SessionDocumentStore] = None,
    session_id: str = "",
    last_scope: str = "",
) -> KnowledgeScope:
    """Choose sources before retrieval; uploaded evidence never selects policy.

    Dynamically inspects session user documents, explicit filenames,
    and conversational context so user documents are never dropped.
    """
    tokens = set(_tokens(question))
    normalized = question.casefold()

    user_docs: list[Evidence] = []
    if user_store and session_id:
        user_docs = user_store.get_session_evidence(session_id)

    user_filenames = {Path(item.source).name.casefold() for item in user_docs if item.source}
    mentions_user_filename = any(fname in normalized for fname in user_filenames if fname)

    refers_to_user_document = (
        mentions_user_filename
        or any(
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
                "in this",
                "that document",
                "the previous one",
            )
        )
        or bool(tokens & {"uploaded", "upload", "policyholder", "proposer", "applicant"})
    )

    if not refers_to_user_document and user_docs and last_scope in {"user", "mixed"}:
        if any(pronoun in normalized.split() for pronoun in ("it", "his", "her", "that", "this", "them")):
            refers_to_user_document = True

    asks_for_policy_comparison = bool(tokens & POLICY_COMPARISON_TERMS) or any(
        phrase in normalized
        for phrase in ("against our rules", "according to policy", "is it verified", "does it meet")
    )

    if refers_to_user_document and asks_for_policy_comparison:
        return "mixed"
    if refers_to_user_document:
        return "user"
    return "application"


# ── Semantic Similarity Retrieval ──────────────────────────────────────────

def _vector_cosine_similarity(query: str, text: str) -> float:
    """Compute cosine similarity between query and candidate text."""
    q_tokens = _tokens(query)
    d_tokens = _tokens(text)
    if not q_tokens or not d_tokens:
        return 0.0

    q_counts = collections.Counter(q_tokens)
    d_counts = collections.Counter(d_tokens)
    common_terms = set(q_counts.keys()) & set(d_counts.keys())
    if not common_terms:
        return 0.0

    dot_product = sum(q_counts[term] * d_counts[term] for term in common_terms)
    q_norm = math.sqrt(sum(v * v for v in q_counts.values()))
    d_norm = math.sqrt(sum(v * v for v in d_counts.values()))
    if q_norm == 0.0 or d_norm == 0.0:
        return 0.0
    return float(dot_product / (q_norm * d_norm))


def retrieve_evidence(
    question: str,
    application_sections: Sequence[KnowledgeSection],
    session_id: str,
    user_store: SessionDocumentStore,
    limit: int = 5,
    last_scope: str = "",
) -> tuple[KnowledgeScope, list[RankedEvidence]]:
    """Pure semantic similarity retrieval using ChromaDB vector search and cosine similarity."""
    scope = route_query(
        question,
        user_store=user_store,
        session_id=session_id,
        last_scope=last_scope,
    )
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

    if not candidates:
        return scope, []

    # 1. Index candidates into ChromaDB vector store
    CHROMA_STORE.index(candidates)

    # 2. Query ChromaDB semantic vector index
    chroma_where = {"session_id": session_id} if scope == "user" else None
    chroma_scores = CHROMA_STORE.query(
        question,
        limit=min(limit * 3, len(candidates)),
        where=chroma_where,
    )

    # 3. Score candidates using vector semantic similarity with relevance threshold
    scored_candidates: list[RankedEvidence] = []
    for item in candidates:
        full_text = f"{item.source} {item.section}\n{item.text}"
        chroma_sim = chroma_scores.get(item.source_id, 0.0)
        v_score = _vector_cosine_similarity(question, full_text)

        # High-confidence vector similarity or keyword cosine overlap
        if v_score > 0.0:
            sim_score = max(chroma_sim, v_score)
        elif chroma_sim >= 0.55:
            sim_score = chroma_sim
        else:
            sim_score = 0.0

        if sim_score >= 0.15:
            scored_candidates.append(
                RankedEvidence(
                    evidence=item,
                    score=round(sim_score, 4),
                    similarity_score=round(sim_score, 4),
                    vector_score=round(sim_score, 4),
                )
            )

    scored_candidates.sort(
        key=lambda result: (
            result.score,
            result.evidence.source_type == "application_kb",
        ),
        reverse=True,
    )

    if scope == "mixed":
        app_candidates = [r for r in scored_candidates if r.evidence.source_type == "application_kb"]
        user_candidates = [r for r in scored_candidates if r.evidence.source_type == "user_document"]
        selected = []
        if app_candidates:
            selected.append(app_candidates[0])
        if user_candidates:
            selected.append(user_candidates[0])
        elif any(c.source_type == "user_document" for c in candidates):
            u_fallback = next(c for c in candidates if c.source_type == "user_document")
            selected.append(RankedEvidence(evidence=u_fallback, score=0.25, similarity_score=0.25, vector_score=0.25))
        remaining = [r for r in scored_candidates if r not in selected]
        selected.extend(remaining)
        return scope, selected[:limit]

    return scope, scored_candidates[:limit]
