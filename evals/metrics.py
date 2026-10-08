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
