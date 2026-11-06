# InsightPilot

A document and data workspace built with Vue 3, FastAPI, and LangGraph.
Inspect Excel beside an AI analyst, approve workbook changes, generate charts,
and review structured document extractions.

![InsightPilot workspace](docs/images/workspace.png)

*Captured from the running frontend in its initial workbook-upload state.*

## Capabilities

- Inspect saved Excel workbooks with sheet tabs, cell coordinates, and a formula bar.
- Ask the Data Analysis Agent for calculations, summaries, and workbook-derived charts.
- Preview and approve column changes, then save, refresh, or restore workbook versions.
- Browse actual answers, charts, and profile runs in Results.
- Extract document fields with multimodal images and an uncertainty-triggered OCR retry.

## Architecture and pipelines

![Implemented platform architecture](docs/images/platform-architecture.svg)

The Vue frontend uses HTTP for files and server-sent events for answers and
processing progress. FastAPI exposes separate analysis and extraction APIs.
Shared model clients follow the configured provider order.

Workbook analysis uses LangGraph and a restricted expression interpreter in a
child process. Mutations follow preview, approval, revision checking, and saved
versions. Charts are rendered on the server from the uploaded workbook.

Document extraction first sends page images to a multimodal model for classification
and fields. A failed or uncertain result gets one OCR-assisted retry. OCR tries
Azure Document Intelligence, Google Document AI, then vision OCR. Schema checks,
confidence thresholds, and conflicting attempts determine human-review flags.

[Workbook pipeline](docs/images/spreadsheet-agent.svg) ·
[Document pipeline](docs/images/document-processing.svg)

## Run locally

Use Python 3.12 and Node.js 18 or newer. From the repository root in Linux or WSL,
create the environment and configure a model provider.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
```

Set credentials and a model ID in `.env`. Provider names are `openai`, `azure`,
and `gemini`. Image-capable models support document extraction and vision OCR.
Dedicated OCR credentials and Tavily definition lookup are optional.

Start the backend in one terminal.

```bash
source .venv/bin/activate
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

Start the frontend in another terminal.

```bash
cd frontend
npm ci
npm run dev -- --host 0.0.0.0 --port 5173
```

Open [the workspace](http://localhost:5173). After `npm run build` in `frontend`,
FastAPI also serves the frontend at [port 8000](http://localhost:8000).
[API documentation](http://localhost:8000/docs) · [Provider setup](RUN.md) ·
[Frontend development](frontend/README.md)

## Evaluation

Measured on 6 November 2026 using synthetic fixtures and configured live APIs.
Every table identifies its cohort. **A-dev** selects analyst temperature using
three tasks, each repeated twice, on one five-row workbook. **A-test** changes
Revenue values and repeats those tasks twice. Its values are held out from
selection, while its schema and task templates match development. **A-flow**
checks the HTTP/SSE application workflow on the development workbook. **X-test**
contains two printed PDF pages with eight labeled fields across two document types.
Extraction settings are fixed before X-test scoring.

[Application results and SSE traces](backend/evals/evaluation_results.json) ·
[Analyst experiments and tool traces](backend/evals/analyst_experiment_results.json) ·
[Definitions, cohorts, and reproduction](docs/EVALUATION.md)

### 1. Analyst correctness and evidence

The execution metric compares tool output with fixed numeric references. Final-answer
scoring checks the requested facts and their region labels. Citation coverage checks
workbook-source event presence. These measures cover the specified facts and sources.
[Execution-result evaluation reference](https://github.com/taoyds/spider/blob/master/evaluation.py)

| Metric | Cohort | Measured result | Scoring rule |
| --- | --- | --- | --- |
| Execution accuracy | A-test | 6/6 | Correct scalar or complete region-to-total mapping |
| Requested-fact correctness | A-test | 6/6 | Expected number, or each region paired with its total |
| Task success | A-test | 6/6 | Correct execution and answer facts, with no tool failure |
| Workbook citation coverage | A-flow calculation questions | 3/3 | Workbook citation event present after each answer |
| Application checks | A-flow | 6/6 | Consent gate, three answers, approved saved column, chart download |

A-test had zero tool failures and a 7.13-second median latency across six requests.
The scoring does not grade every free-form claim for entailment. Full-answer
faithfulness and calibrated confidence remain unmeasured. Repeated requests on
one workbook are a small smoke sample.

### 2. Document extraction quality

Field scores compare normalized named values with annotations. A wrong nonempty
value contributes both a false positive and a false negative. CER uses character
edit distance divided by reference characters and can exceed 1 with insertions.
[Field metrics](https://docs.cloud.google.com/document-ai/docs/evaluate) ·
[CER definition](https://github.com/huggingface/evaluate/blob/main/metrics/cer/cer.py)

| Metric | Cohort | Measured result | Denominator and scope |
| --- | --- | --- | --- |
| Classification accuracy | X-test | 2/2 | PAN card and benefit illustration |
| Field micro precision / recall / F1 | X-test | 100% / 100% / 100% | TP=8, FP=0, FN=0 across eight labeled fields |
| Whole-document exact match | X-test | 2/2 | Correct type and all four expected fields |
| Normalized CER | X-test fields / separate OCR page | Fields 0/93 = 0.000, page 0.000 | Field edit errors/reference characters and full-page vision OCR CER |
| Export availability | X-test job | 4/4 HTTP 200 | Documents JSON, review JSON, evaluation JSON, XLSX |

The two-page extraction took 14.00 seconds and completed through the primary
multimodal path. A separate OCR request exercised provider fallback. Azure DNS
resolution failed and Google Document AI billing was disabled. Vision OCR completed.
Handwriting, degraded scans, and the other supported document types need labeled
validation before broader accuracy claims.

### 3. Parameter experiments and choices

Temperature is changed one factor at a time with the same provider configuration,
questions, and workbook. Experiments run sequentially in baseline-first order.
The OCR threshold replay uses saved scores from X-test and is descriptive.

| Setting | Cohort | Measured result | Decision |
| --- | --- | --- | --- |
| Analyst temperature 0.1 | A-dev, 6 requests | 6/6 successful, median 5.54 s | Retained baseline after accuracy tie |
| Analyst temperature 0.0 | A-dev, 6 requests | 6/6 successful, median 5.85 s | No accuracy gain observed |
| Analyst temperature 0.2 | A-dev, 6 requests | 6/6 successful, median 5.57 s | No accuracy gain observed |
| Field threshold 0.75 / 0.85 / 0.95 | X-test score replay | 8/8 accepted at every threshold | Retain 0.85, sample cannot distinguish settings |
| Handwriting penalty / OCR retry budget | Fixed policy | 0.20 / one logical retry | Safety choices, sensitivity unmeasured |

All tested analyst temperatures tied on task success, so the predefined tie rule
retained 0.1. A-test confirmed 6/6 at that setting. Latency differences have no
statistical significance established by this sample. Model sampling for image
extraction remains provider-default. No model-weight fine-tuning was performed.

## Reproduce the checks

```bash
source .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd backend
pytest -q
python -m evals.run_all_evaluations
python -m evals.run_all_evaluations --live
python -m evals.analyst_experiments --live --repetitions 2
```

The default evaluation runs local sandbox checks. Live runs send generated fixtures
to configured services. The HTTP runner needs the backend on port 8000 and removes
its temporary workbook session afterward. Document job outputs remain inspectable.
The temperature experiment uses temporary files and process-local datasets.

Run frontend checks from the repository root.

```bash
cd frontend
npm test
npm run build
```

The final regression run passed 110 backend tests and 9 frontend tests.
The frontend production build succeeded.

## Storage and current limits

Workbook files, versions, chart metadata, and document jobs are stored locally.
Browser storage holds workspace selection and answer history. Conversation
checkpoints and pending previews are process-local. Restarting the backend
invalidates pending approvals.

Session UUIDs currently identify workspaces. Authentication, tenant isolation,
production concurrency testing, and broader labeled evaluation remain future work.
The restricted interpreter shares its backend host's operating-system context.
Runtime confidence is heuristic and requires separate calibration.

## Repository layout

```text
backend/
  main.py                    FastAPI application and frontend serving
  excel_agent/               Analysis, restricted execution, workbook changes
  document_intelligence/     Multimodal extraction, OCR retry, review, exports
  datapilot/                 Providers, configuration, guardrails, latency
  evals/                     Reproducible evaluation and measured traces
  tests/                     Backend regression tests
frontend/src/                Vue screens, API client, design tokens
docs/                        Architecture, pipelines, evaluation methods
```
