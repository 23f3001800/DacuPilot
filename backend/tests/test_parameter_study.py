import pytest

from evals.parameter_study import retrieval_metrics, score_claims


def test_retrieval_counts_irrelevant_and_missing_sections():
    result = retrieval_metrics([
        {"relevant": ["A", "B"], "returned": ["A", "C"]},
        {"relevant": [], "returned": ["C"]},
    ])
    assert result["tp"] == 1
    assert result["fp"] == 2
    assert result["fn"] == 1
    assert result["precision"] == pytest.approx(1 / 3)
    assert result["recall"] == 0.5
    assert result["f1"] == 0.4


def test_faithfulness_and_citation_coverage_are_independent():
    result = score_claims("Annual leave is 24 days.", [{"citation": "Handbook — Leave", "text": "Annual leave is 24 days."}], {
        "claims": [{"claim": "Annual leave is 24 days.", "supported": True,
                    "citation": "", "support_source": "Handbook — Leave", "reference_quote": "Annual leave is 24 days."}],
        "reference_fact_matches": [True],
    }, 1)
    assert result["supported"] == 1
    assert result["covered"] == 0
    assert result["correct_citations"] == 0


def test_a_fabricated_judge_quote_cannot_count_as_support():
    result = score_claims("Annual leave is 50 days. Source: [Handbook — Leave]", [{"citation": "Handbook — Leave", "text": "Annual leave is 24 days."}], {
        "claims": [{"claim": "Annual leave is 50 days.", "supported": True,
                    "citation": "Handbook — Leave", "support_source": "Handbook — Leave", "reference_quote": "Annual leave is 50 days."}],
        "reference_fact_matches": [False],
    }, 1)
    assert result["supported"] == 0
    assert result["covered"] == 1
    assert result["correct_citations"] == 0
