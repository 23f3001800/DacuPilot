"""Measure synthetic cases using real application code and optional live APIs."""

import argparse
import hashlib
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import time
from uuid import uuid4

import httpx
from openpyxl import Workbook

from datapilot.config import get_config
from document_intelligence.schemas.documents import DOCUMENT_DATA_FIELDS
from document_intelligence.utils.evaluator import StageGateEvaluator
from excel_agent.engine import PythonSandboxREPL
from excel_agent.loader import load_real_world_excel
from evals.metrics import field_metrics

ROOT = Path(__file__).resolve().parents[1]


def workbook_bytes():
    book = Workbook()
    sheet = book.active
    sheet.title = "Sales"
    for row in [
        ["Region", "Revenue", "Cost", "Units"],
        ["North", 150, 90, 10], ["South", 80, 50, 6],
        ["North", 50, 30, 4], ["West", 120, None, 8], ["East", 100, 60, 7],
    ]:
        sheet.append(row)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def stream(client, path, payload=None, **kwargs):
    started = time.perf_counter()
    events, trace = [], []
    done = False
    with client.stream("POST", path, json=payload, **kwargs) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            value = line[5:].strip()
            if value == "[DONE]":
                done = True
                continue
            event = json.loads(value)
            events.append(event)
            kind = event.get("event", event.get("type"))
            if kind == "complete":
                done = True
            if kind != "token":
                trace.append({
                    "at_ms": round((time.perf_counter() - started) * 1000, 2),
                    "kind": kind,
                    **{key: event[key] for key in ("text", "tool", "success", "stage", "status", "ocr_provider", "failure_type") if key in event},
                })
    answer = "".join(event.get("text", "") for event in events if event.get("event") == "token")
    evaluation = {}
    for event in events:
        if event.get("event") == "final_answer":
            answer = event["text"]
        if event.get("event") == "evaluation":
            evaluation = event.get("payload", {})
    return {"answer": answer, "evaluation": evaluation, "events": events,
            "trace": trace, "completed": done,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2)}


def record(case_id, result, checks, expected=None):
    return {"id": case_id, "passed": all(checks.values()), "checks": checks,
            "expected": expected, "answer": result.get("answer"),
            "latency_ms": result.get("latency_ms"), "evaluation": result.get("evaluation"),
            "trace": result.get("trace", [])}


def summary(cases):
    passed = sum(case["passed"] for case in cases)
    return {"passed": passed, "total": len(cases), "rate": passed / len(cases) if cases else None}


def has_number(text, number):
    numbers = re.findall(r"(?<![\w.])\d+(?:\.\d+)?", text.replace(",", ""))
    return any(float(value) == float(number) for value in numbers)


def evaluate_sandbox():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "evaluation-sales.xlsx"
        path.write_bytes(workbook_bytes())
        frame, _ = load_real_world_excel(path)
        sandbox = PythonSandboxREPL(frame)
        calculations = []
        for code, expected in [
            ("print(len(df))", "5"), ("print(df['Revenue'].sum())", "500"),
            ("print(df['Revenue'].mean())", "100.0"), ("print(df['Cost'].isna().sum())", "1"),
        ]:
            started = time.perf_counter()
            actual = sandbox.execute_code(code).strip()
            calculations.append({"code": code, "expected": expected, "actual": actual,
                                 "passed": actual == expected,
                                 "latency_ms": round((time.perf_counter() - started) * 1000, 2)})
        attacks = []
        for code in ["import os", "open('/etc/hosts')", "eval('1+1')", "df['Revenue'] = 0", "df.drop(columns=['Revenue'], inplace=True)"]:
            actual = sandbox.execute_code(code)
            blocked = actual.lower().startswith("error") and "timed out" not in actual.lower()
            attacks.append({"code": code, "passed": blocked, "actual": actual})
    return {"calculations": calculations, "calculation_summary": summary(calculations),
            "safety_cases": attacks, "safety_summary": summary(attacks)}


def evaluate_data_agent(client):
    session = str(uuid4())
    cases = []
    try:
        uploaded = client.post("/api/data/upload", data={"thread_id": session},
                               files={"file": ("evaluation-sales.xlsx", workbook_bytes())})
        uploaded.raise_for_status()
        consent = client.post("/api/chat/stream", json={"thread_id": session, "message": "Total Revenue", "processing_consent": False})
        cases.append({"id": "consent-required", "passed": consent.status_code == 403, "http_status": consent.status_code})
        for name, question, expected in [
            ("total-revenue", "What is total Revenue? Answer briefly.", [500]),
            ("regional-revenue", "Sum Revenue by Region. Show each region and its total.", [200, 120, 100, 80]),
            ("average-revenue", "What is the mean Revenue per row? Answer briefly.", [100]),
        ]:
            result = stream(client, "/api/chat/stream", {"thread_id": session, "message": question, "processing_consent": True})
            checks = {
                "stream_completed": result["completed"],
                "expected_numbers": all(has_number(result["answer"], number) for number in expected),
                "tool_succeeded": any(event.get("event") == "tool_result" and event.get("tool") == "execute_pandas_code" and event.get("success") for event in result["events"]),
                "no_tool_failure": not any(event.get("event") == "tool_result" and event.get("success") is False for event in result["events"]),
                "workbook_cited": any(event.get("event") == "citations" for event in result["events"]),
            }
            cases.append(record(name, result, checks, expected))
        result = stream(client, "/api/chat/stream", {"thread_id": session,
                        "message": "Add column Profit using df['Revenue'] - df['Cost']", "processing_consent": True})
        preview = next((event["preview"] for event in result["events"] if event.get("event") == "change_preview"), None)
        before = client.get("/api/data/schema", params={"thread_id": session}).json()
        if preview:
            applied = client.post("/api/data/column/apply", json={"thread_id": session, "operation_id": preview["operation_id"]})
            applied.raise_for_status()
        after = client.get("/api/data/preview", params={"thread_id": session}).json()
        profits = [row.get("Profit") for row in after.get("rows", [])]
        cases.append(record("approved-column-change", result, {
            "preview_returned": preview is not None, "unchanged_before_approval": "Profit" not in before["columns"],
            "saved_values_match": profits == [60, 30, 20, None, 40]}, [60, 30, 20, None, 40]))
        chart = client.post("/api/data/charts/generate", json={"thread_id": session, "column": "Revenue", "category_column": "Region"})
        chart.raise_for_status()
        image = client.get(chart.json()["url"])
        cases.append({"id": "generated-chart", "passed": image.status_code == 200 and "<svg" in image.text, "title": chart.json()["title"]})
        return {"cases": cases, "summary": summary(cases)}
    finally:
        client.delete("/api/data/workbook", params={"thread_id": session})


def ocr_fixture():
    import pymupdf
    pages = [
        {"type": "PAN_CARD", "fields": {"pan_number": "ABCDE1234F", "full_name": "ALEX EXAMPLE", "father_name": "MORGAN EXAMPLE", "date_of_birth": "1990-01-02"},
         "lines": ["INCOME TAX DEPARTMENT", "GOVT. OF INDIA", "PERMANENT ACCOUNT NUMBER", "PAN: ABCDE1234F", "Name: ALEX EXAMPLE", "Father's Name: MORGAN EXAMPLE", "Date of Birth: 1990-01-02", "SYNTHETIC SAMPLE - NOT A VALID ID"]},
        {"type": "BENEFIT_ILLUSTRATION", "fields": {"application_number": "TEST-2026-001", "policyholder_name": "ALEX EXAMPLE", "date": "2026-11-06", "place": "EXAMPLE CITY"},
         "lines": ["BENEFIT ILLUSTRATION", "Application Number: TEST-2026-001", "Policyholder Name: ALEX EXAMPLE", "Date: 2026-11-06", "Place: EXAMPLE CITY", "SYNTHETIC EVALUATION SAMPLE"]},
    ]
    with pymupdf.open() as document:
        for reference in pages:
            page = document.new_page(width=800, height=600)
            for index, line in enumerate(reference["lines"]):
                page.insert_text((45, 65 + index * 48), line, fontsize=19, fontname="helv")
        image = document[0].get_pixmap(alpha=False).tobytes("png")
        return document.tobytes(), image, pages


def normalized(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def evaluate_ocr(client):
    from document_intelligence.utils.ocr import MultimodalOCRProcessor
    pdf, image, references = ocr_fixture()
    result = stream(client, "/api/documents/process/stream", data={"external_processing_consent": "true"},
                    files=[("files", ("synthetic-evaluation.pdf", pdf, "application/pdf"))])
    completed = next((event["result"] for event in result["events"] if event.get("type") == "complete"), None)
    if completed is None:
        return {"status": "failed", "trace": result["trace"], "errors": [event for event in result["events"] if event.get("type") == "error"]}
    documents = completed["documents"]
    comparisons = []
    classification_correct = 0
    document_exact_matches = 0
    for index, expected in enumerate(references, 1):
        document = next((doc for doc in documents if index in doc.get("pages", [doc.get("page_number")])), {})
        classification_correct += document.get("document_type") == expected["type"]
        predicted_type = document.get("document_type")
        predicted_fields = document.get("extraction", {}).get(DOCUMENT_DATA_FIELDS.get(predicted_type, ""), {})
        fields = predicted_fields if predicted_type == expected["type"] else {}
        document_exact_matches += document.get("document_type") == expected["type"] and all(
            normalized(fields.get(name, {}).get("value")) == normalized(value)
            for name, value in expected["fields"].items()
        )
        for name, value in expected["fields"].items():
            actual = fields.get(name, {}).get("value")
            comparisons.append({"page": index, "field": name, "expected": value, "actual": actual,
                                "exact_match": normalized(actual) == normalized(value),
                                "cer": StageGateEvaluator.calculate_cer(value, actual)})
        for name, field in predicted_fields.items():
            if predicted_type != expected["type"] or name not in expected["fields"]:
                comparisons.append({"page": index, "field": name, "expected": None,
                                    "actual": field.get("value"), "exact_match": False,
                                    "cer": StageGateEvaluator.calculate_cer("", field.get("value"))})
    exports = []
    for kind, url in completed["outputs"].items():
        response = client.get(url)
        exports.append({"kind": kind, "http_status": response.status_code, "bytes": len(response.content)})
    raw_start = time.perf_counter()
    raw = MultimodalOCRProcessor()._ocr_with_fallback(image, "image/png")
    raw_cer = StageGateEvaluator.calculate_cer(normalized("\n".join(references[0]["lines"])), normalized(raw.text))
    sweep = []
    for threshold in (0.75, 0.85, 0.95):
        accepted = 0
        for document in documents:
            block = document.get("extraction", {}).get(DOCUMENT_DATA_FIELDS.get(document["document_type"], ""), {})
            accepted += sum(field.get("final_field_score", 0) >= threshold and field.get("regex_match", False) and bool(field.get("value")) for field in block.values())
        sweep.append({"threshold": threshold, "accepted_fields": accepted, "total_fields": len(comparisons)})
    return {"status": "completed", "page_count": completed["page_count"], "document_count": completed["document_count"],
            "cohort": "X-test: two generated printed PDF pages, eight single-value fields; no parameter selection on this cohort",
            "classification_correct": classification_correct, "classification_total": len(references), "fields": comparisons,
            "field_metrics": field_metrics(comparisons), "document_exact_matches": document_exact_matches,
            "field_exact_matches": sum(field["exact_match"] for field in comparisons),
            "field_total": sum(len(reference["fields"]) for reference in references),
            "mean_field_cer": sum(field["cer"] for field in comparisons) / len(comparisons),
            "raw_ocr": {"provider": raw.provider, "normalized_cer": raw_cer,
                        "latency_ms": round((time.perf_counter() - raw_start) * 1000, 2)},
            "threshold_sensitivity": sweep, "exports": exports, "latency_ms": result["latency_ms"],
            "stage_latencies": completed.get("stage_latencies"), "trace": result["trace"],
            "documents": documents, "review_report": completed["review_report"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Send synthetic fixtures to configured external APIs")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--output", type=Path, default=ROOT / "evals" / "evaluation_results.json")
    args = parser.parse_args()
    started = time.perf_counter()
    settings = get_config()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    report = {"schema_version": 2, "timestamp": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
              "source_revision": revision, "uncommitted_source": bool(subprocess.check_output(["git", "diff", "--name-only"], cwd=ROOT)),
              "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "live": args.live, "scope": "Small synthetic smoke evaluation; no population accuracy or calibration estimate",
              "settings": {"data_temperature": 0.1,
                           "field_threshold": settings.field_confidence_threshold, "handwriting_penalty": settings.handwriting_penalty},
              "sandbox": evaluate_sandbox()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.live:
        with httpx.Client(base_url=args.base_url, timeout=240) as client:
            client.get("/api/health").raise_for_status()
            report["runtime"] = client.get("/api/documents/settings").json()
            report["runtime"].pop("active_endpoint", None)
            for name, run in (("data_agent", evaluate_data_agent), ("ocr", evaluate_ocr)):
                print(f"Running {name}", flush=True)
                try:
                    report[name] = run(client)
                except Exception as error:
                    report[name] = {"status": "failed", "error_type": type(error).__name__, "message": str(error)}
                args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Measured results saved to {args.output}", flush=True)


if __name__ == "__main__":
    main()
