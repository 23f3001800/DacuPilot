"""Run bounded, one-factor analyst experiments on synthetic workbook cohorts."""

import argparse
import ast
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def calculation_matches(output, expected):
    """Compare a printed scalar or complete regional result to a fixed oracle."""
    text = str(output).strip()
    if not isinstance(expected, dict):
        try:
            return math.isclose(float(text), expected, rel_tol=1e-9, abs_tol=1e-9)
        except ValueError:
            return False
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        parsed = {}
        for line in text.splitlines():
            match = re.fullmatch(r"\s*([A-Za-z][A-Za-z ]*?)\s+(-?\d+(?:\.\d+)?)\s*", line)
            if match:
                if match[1] in parsed:
                    return False
                parsed[match[1]] = float(match[2])
            elif line.strip() and line.strip() != "Region" and not line.startswith("Name:"):
                return False
    return isinstance(parsed, dict) and parsed == expected


def answer_matches(answer, expected):
    """Score only the requested numeric facts, including region association."""
    text = str(answer).replace(",", "")
    if isinstance(expected, dict):
        return all(
            re.search(rf"\b{region}\b[^\n\d]{{0,50}}{value}(?:\.0+)?(?!\d|\.\d)", text, re.I)
            for region, value in expected.items()
        )
    return any(float(value) == expected for value in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", text))


def summarize(cases):
    return {
        "total": len(cases),
        "execution_correct": sum(case["execution_correct"] for case in cases),
        "answer_facts_correct": sum(case["answer_facts_correct"] for case in cases),
        "task_success": sum(case["task_success"] for case in cases),
        "tool_failures": sum(case["tool_failure"] for case in cases),
        "median_latency_ms": round(statistics.median(case["latency_ms"] for case in cases), 2),
        "latency_range_ms": [min(case["latency_ms"] for case in cases), max(case["latency_ms"] for case in cases)],
    }


async def evaluate(temperature, cohort, repetitions):
    # Keep heavy application imports out of multiprocessing's spawned entry point.
    from langchain_core.messages import HumanMessage, ToolMessage
    from openpyxl import Workbook
    from datapilot.llm_provider import create_chat_model
    from excel_agent import agent
    from excel_agent.engine import PythonSandboxREPL
    from excel_agent.loader import load_real_world_excel

    values = [150, 80, 50, 120, 100] if cohort == "A-dev" else [210, 140, 90, 60, 100]
    regions = ["North", "South", "North", "West", "East"]
    grouped = {region: sum(value for label, value in zip(regions, values) if label == region) for region in set(regions)}
    tasks = [
        ("total", "What is total Revenue? Answer briefly.", sum(values)),
        ("mean", "What is the mean Revenue per row? Answer briefly.", sum(values) / len(values)),
        ("regions", "Sum Revenue by Region. Show each region and its total.", grouped),
    ]
    cases = []
    original_model = agent.get_llm
    agent.get_llm = lambda: create_chat_model(temperature=temperature, streaming=True, timeout=90, max_retries=1)
    try:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic-sales.xlsx"
            workbook = Workbook()
            workbook.active.append(["Region", "Revenue", "Cost", "Units"])
            for region, revenue, cost, units in zip(regions, values, [90, 50, 30, None, 60], [10, 6, 4, 8, 7]):
                workbook.active.append([region, revenue, cost, units])
            workbook.save(path)
            frame, schema = load_real_world_excel(path)
            for repetition in range(repetitions):
                for name, question, expected in tasks:
                    session = str(uuid4())
                    agent._datasets[session] = agent.DatasetContext(frame, schema, PythonSandboxREPL(frame))
                    started = time.perf_counter()
                    case = {"id": name, "repetition": repetition + 1, "expected": expected,
                            "execution_correct": False, "answer_facts_correct": False,
                            "task_success": False, "tool_failure": False, "tools": [], "answer": ""}
                    try:
                        result = await asyncio.wait_for(agent.compiled_graph.ainvoke(
                            {"messages": [HumanMessage(content=question)], "thread_id": session, "tool_rounds": 0},
                            {"configurable": {"thread_id": session}},
                        ), timeout=240)
                        messages = result["messages"]
                        case["tools"] = [{"name": message.name, "output": str(message.content)}
                                         for message in messages if isinstance(message, ToolMessage)]
                        case["tool_calls"] = [call for message in messages for call in getattr(message, "tool_calls", [])]
                        case["answer"] = str(messages[-1].content)
                        case["execution_correct"] = any(tool["name"] == "execute_pandas_code" and calculation_matches(tool["output"], expected) for tool in case["tools"])
                        case["answer_facts_correct"] = bool(answer_matches(case["answer"], expected))
                        case["tool_failure"] = any(tool["output"].lower().startswith("error") for tool in case["tools"])
                        case["task_success"] = case["execution_correct"] and case["answer_facts_correct"] and not case["tool_failure"]
                    except Exception as error:
                        case["error_type"] = type(error).__name__
                        case["tool_failure"] = True
                    finally:
                        agent._datasets.pop(session, None)
                        agent.reset_agent_conversation(session)
                    case["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
                    cases.append(case)
                    print(f"{cohort} temperature={temperature} {name} repeat={repetition + 1} success={case['task_success']}", flush=True)
    finally:
        agent.get_llm = original_model
    return {"cohort": cohort, "temperature": temperature, "cases": cases, "summary": summarize(cases)}


async def run(args):
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "uncommitted_source": bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT)),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "Three tasks on each of two five-row synthetic workbooks; repeated requests are not independent datasets",
        "selection_rule": "Highest A-dev task-success count; ties retain baseline temperature 0.1",
        "development": [],
    }
    def save():
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for temperature in (0.1, 0.0, 0.2):
        report["development"].append(await evaluate(temperature, "A-dev", args.repetitions))
        save()
    selected = max(report["development"], key=lambda result: result["summary"]["task_success"])["temperature"]
    report["selected_temperature"] = selected
    report["held_out"] = await evaluate(selected, "A-test", args.repetitions)
    report["baseline_shares_held_out_run"] = selected == 0.1
    if selected != 0.1:
        report["baseline_held_out"] = await evaluate(0.1, "A-test", args.repetitions)
    save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--output", type=Path, default=ROOT / "evals" / "analyst_experiment_results.json")
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("repetitions must be positive")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
