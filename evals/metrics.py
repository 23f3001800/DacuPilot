"""Evaluation matrices for DocuPilot.

Three focused matrices inspired by the DevDocs-AI evaluation framework
(see /home/vikas/DevDocs-AI/evals/):

1. Pipeline Quality Matrix  — classification accuracy, field extraction CER,
   confidence calibration across a completed pipeline run.
2. Throughput Matrix        — latency per stage, pages/sec, total time.
3. Routing Matrix           — automation vs human-review split, flag reasons.
"""

from __future__ import annotations

import math
from typing import Any, Sequence


# ── Matrix 1: Pipeline Quality ───────────────────────────────────────────────

def pipeline_quality_matrix(documents: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Compute quality metrics from pipeline output documents.

    Returns classification confidence stats, field-level confidence
    distribution, and validation pass-rates.
    """
    if not documents:
        return {"error": "No documents to evaluate"}

    cls_scores: list[float] = []
    field_scores: list[float] = []
    validation_pass = 0
    validation_total = 0

    for doc in documents:
        conf = doc.get("classification_confidence", 0.0)
        if isinstance(conf, (int, float)) and math.isfinite(conf):
            cls_scores.append(conf)

        matrix = doc.get("extraction", {}).get("system_evaluation_matrix", {})
        failures = matrix.get("validation_failures", [])
        validation_total += 1
        if not failures:
            validation_pass += 1

        # Collect per-field confidence scores from the extraction payload
        extraction = doc.get("extraction", {})
        for key, block in extraction.items():
            if not isinstance(block, dict) or key in (
                "document_type", "text_medium", "system_evaluation_matrix",
            ):
                continue
            for _fname, fval in block.items():
                if isinstance(fval, dict) and "final_field_score" in fval:
                    score = fval["final_field_score"]
                    if isinstance(score, (int, float)) and math.isfinite(score):
                        field_scores.append(score)

    n_cls = len(cls_scores)
    n_fld = len(field_scores)

    return {
        "classification": {
            "count": n_cls,
            "mean": round(sum(cls_scores) / n_cls, 4) if n_cls else 0.0,
            "min": round(min(cls_scores), 4) if cls_scores else 0.0,
            "max": round(max(cls_scores), 4) if cls_scores else 0.0,
        },
        "field_confidence": {
            "count": n_fld,
            "mean": round(sum(field_scores) / n_fld, 4) if n_fld else 0.0,
            "min": round(min(field_scores), 4) if field_scores else 0.0,
            "max": round(max(field_scores), 4) if field_scores else 0.0,
        },
        "validation_pass_rate": (
            round(validation_pass / validation_total, 4)
            if validation_total else 0.0
        ),
    }


# ── Matrix 2: Throughput ─────────────────────────────────────────────────────

def throughput_matrix(
    page_count: int,
    total_latency_ms: float,
    stage_latencies: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compute throughput metrics for a pipeline run.

    *stage_latencies* is an optional ``{stage_name: ms}`` mapping collected
    from the latency-instrumented pipeline.
    """
    result: dict[str, Any] = {
        "total_pages": page_count,
        "total_ms": round(total_latency_ms, 2),
        "avg_ms_per_page": (
            round(total_latency_ms / page_count, 2) if page_count else 0.0
        ),
        "pages_per_second": (
            round(page_count / (total_latency_ms / 1000), 2)
            if total_latency_ms > 0 else 0.0
        ),
    }
    if stage_latencies:
        result["stage_breakdown_ms"] = {
            k: round(v, 2) for k, v in stage_latencies.items()
        }
    return result


# ── Matrix 3: Routing ────────────────────────────────────────────────────────

def routing_matrix(
    documents: Sequence[dict[str, Any]],
    review_report: dict[str, Any],
) -> dict[str, Any]:
    """Summarise how documents were routed and why flags were raised."""
    type_counts: dict[str, int] = {}
    route_counts: dict[str, int] = {}

    for doc in documents:
        dtype = doc.get("document_type", "UNKNOWN")
        type_counts[dtype] = type_counts.get(dtype, 0) + 1

        matrix = doc.get("extraction", {}).get("system_evaluation_matrix", {})
        route = matrix.get("final_routing_decision", "UNKNOWN")
        route_counts[route] = route_counts.get(route, 0) + 1

    flagged = review_report.get("flagged_fields", [])
    reason_counts: dict[str, int] = {}
    for flag in flagged:
        reason = flag.get("reason", "UNKNOWN")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    n = len(documents)
    auto = route_counts.get("AUTOMATED_PROCESSING", 0)

    return {
        "document_types": type_counts,
        "routing_decisions": route_counts,
        "automation_rate": round(auto / n, 4) if n else 0.0,
        "total_flags": len(flagged),
        "flags_by_reason": reason_counts,
        "human_review_required": review_report.get("human_review_required", False),
    }


# ── Matrix 4: Retrieval Evaluation (Document Assistance) ──────────────────────

def retrieval_evaluation_matrix(
    cases: Sequence[dict[str, Any]],
    k: int = 5,
) -> dict[str, Any]:
    """Measure hybrid retrieval quality (BM25 + RRF + CrossEncoder rerank).

    Each case in *cases* should provide:
    - ``retrieved_ids``: sequence of retrieved chunk or section IDs
    - ``relevant_ids``: set or list of expected ground-truth IDs
    - ``top_score`` (optional): score of the highest-ranked chunk
    - ``latency_ms`` (optional): query retrieval latency in milliseconds
    """
    if not cases:
        return {"error": "No cases to evaluate"}

    hit_rates = []
    reciprocal_ranks = []
    recalls = []
    precisions = []
    top_scores = []
    latencies = []

    for case in cases:
        retrieved = list(dict.fromkeys(case.get("retrieved_ids", [])[:k]))
        relevant = set(case.get("relevant_ids", []))
        if not relevant:
            continue

        hits = [doc_id in relevant for doc_id in retrieved]
        has_hit = any(hits)
        hit_rates.append(1.0 if has_hit else 0.0)

        # Reciprocal rank (1 / first hit rank)
        rr = 0.0
        for rank, is_hit in enumerate(hits, start=1):
            if is_hit:
                rr = 1.0 / rank
                break
        reciprocal_ranks.append(rr)

        # Recall@k and Precision@k
        num_hits = sum(hits)
        recalls.append(num_hits / len(relevant) if relevant else 0.0)
        precisions.append(num_hits / len(retrieved) if retrieved else 0.0)

        if "top_score" in case:
            top_scores.append(float(case["top_score"]))
        if "latency_ms" in case:
            latencies.append(float(case["latency_ms"]))

    n = len(hit_rates) or 1
    return {
        "case_count": len(cases),
        "hit_rate": round(sum(hit_rates) / n, 4),
        "mrr": round(sum(reciprocal_ranks) / n, 4),
        "recall_at_k": round(sum(recalls) / n, 4),
        "precision_at_k": round(sum(precisions) / n, 4),
        "avg_top_score": round(sum(top_scores) / len(top_scores), 4) if top_scores else None,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
    }


# ── Matrix 5: Answer Grounding (Document Assistance) ─────────────────────────

def answer_grounding_matrix(
    records: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Measure answer correctness, keyword grounding, and citation validity.

    Each record in *records* should provide:
    - ``answer``: generated response text
    - ``ground_truth``: reference answer string
    - ``sources``: sequence of cited source strings
    """
    if not records:
        return {"error": "No records to evaluate"}

    stop_words = {
        "a", "an", "and", "are", "at", "be", "can", "do", "for", "from",
        "in", "is", "it", "of", "on", "or", "the", "to", "under", "within", "you",
    }

    keyword_coverages = []
    citation_coverages = []
    answer_successes = []

    for item in records:
        answer = str(item.get("answer", "")).strip()
        gt = str(item.get("ground_truth", "")).strip()
        sources = list(item.get("sources", []))

        # 1. Answer presence
        has_answer = bool(answer) and not answer.startswith("I don't have enough evidence")
        answer_successes.append(1.0 if has_answer else 0.0)

        # 2. Citation coverage
        has_sources = len(sources) > 0 or ("Source:" in answer)
        citation_coverages.append(1.0 if has_sources else 0.0)

        # 3. Keyword grounding coverage
        expected = {
            w for w in re.findall(r"[a-z0-9]+", gt.lower())
            if len(w) > 2 and w not in stop_words
        }
        if expected:
            actual = set(re.findall(r"[a-z0-9]+", answer.lower()))
            cov = len(expected & actual) / len(expected)
            keyword_coverages.append(cov)
        else:
            keyword_coverages.append(1.0 if answer else 0.0)

    n = len(records)
    return {
        "record_count": n,
        "answer_rate": round(sum(answer_successes) / n, 4),
        "citation_coverage": round(sum(citation_coverages) / n, 4),
        "keyword_coverage": round(sum(keyword_coverages) / n, 4),
    }
