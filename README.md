# InsightPilot

A document and data workspace built with Vue 3, FastAPI, and LangGraph.
Inspect an Excel workbook beside an AI analyst, approve changes before saving,
ask questions about company documents, and review OCR-extracted fields.

![InsightPilot workspace with an uploaded workbook and a generated chart](docs/images/workspace.png)

*Captured from the running frontend using a synthetic five-row workbook. The
chart and answer were generated from that workbook.*

## What the application does

| Area | Capabilities |
| --- | --- |
| Workspace | Upload, inspect, refresh, download, and delete saved Excel workbooks. Switch sheets and inspect cells in an Excel-style grid. |
| Data Analysis Agent | Stream answers and activity, calculate workbook summaries, generate charts, and preview column changes for approval. |
| Results | Browse saved answers, generated charts, and workbook profile runs from the current session. |
| Company Help | Answer general questions and retrieve company handbook or privacy-policy evidence with source citations. Opens from the corner assistant button. |
| Documents | Segment PDFs and images, recognize text, classify ten document types, extract fields, flag review items, and download JSON or Excel outputs. |

## Architecture and pipelines

![Implemented platform architecture](docs/images/platform-architecture.svg)

The Vue frontend sends HTTP requests and consumes server-sent events from one
FastAPI application. Data analysis, company assistance, and document extraction
have separate APIs and processing paths. OpenAI-compatible model clients use
the configured provider order.

- Workbook analysis uses a restricted expression evaluator in an isolated child
  process. Column changes follow a separate preview, approval, revision-check,
  and workbook-version flow. Charts are rendered on the server from real data.
- Company retrieval combines token-count cosine similarity with Chroma vector
  scores when Chroma is available. The active sources are the Nimbus Orchard
  handbook and privacy policy. General answers use a separate source-free path.
- OCR tries Azure Document Intelligence, Google Document AI, then a vision
  model. Classification and field extraction follow OCR. Schema validation,
  handwriting adjustments, and confidence thresholds determine review flags.

[Workbook pipeline](docs/images/spreadsheet-agent.svg) ·
[OCR pipeline](docs/images/document-processing.svg) ·
[Redesign decisions](docs/WORKSPACE_REDESIGN.md)

## Run locally

Use Python 3.12 and Node.js 18 or newer. Run these commands from the repository
root in Linux or WSL.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
```

Set the credentials and model ID for at least one provider in `.env`. The
available provider names are `openai`, `azure`, and `gemini`. Dedicated OCR
credentials are optional when the configured model supports image input.
Tavily credentials enable the analyst's external definition lookup.

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

Open [the workspace](http://localhost:5173). The backend also serves the built
frontend at [port 8000](http://localhost:8000) after `npm run build` in
`frontend`. API documentation is available at [Swagger UI](http://localhost:8000/docs).

[Provider setup](RUN.md) · [Frontend development](frontend/README.md)

## Evaluation results

Measured on **6 November 2026**, using code revision `5faf9ae`, Python 3.12.3,
and the configured `gpt-5-mini` deployment as the primary language model.
The suite took 80.26 seconds. Inputs were a generated five-row workbook, three
handbook reference questions, four assistance behavior cases, and two generated
printed document pages. Each case ran once.

These are small smoke evaluations. Percentages describe the stated cases.
Model-reported confidence, retrieval scores, correctness checks, and groundedness
checks are reported separately. Timings include local and provider variability.

[Raw results and per-case traces](backend/evals/evaluation_results.json) ·
[Methods and trace examples](docs/EVALUATION.md)

### Groundedness

| Check | Result | Meaning |
| --- | --- | --- |
| Target fact supported by the expected handbook section | 3 / 3 | Annual leave of 24 days, Grove price of USD 249, and a 16-character minimum password were present with the expected citation. |
| Returned citations resolve to loaded source sections | 3 / 3 | Citation source and section labels matched the active corpus. |
| General answer avoids company citations | 1 / 1 | The Tokyo answer carried no document citation. |
| Claim-by-claim entailment and confidence calibration | Unmeasured | The suite checks selected facts and citation identities. It does not establish support for every possible generated claim. |

### Data Analysis Agent

| Evaluation | Result | Observed evidence |
| --- | --- | --- |
| Live application checks | 6 / 6 | Consent rejection, three numeric answers, approved modification, and generated SVG download. |
| Total Revenue | Pass · 5,527 ms | Answer contained 500, a successful calculation event, and workbook evidence. |
| Revenue by Region | Pass · 5,513 ms | Expected numbers were North 200, West 120, East 100, and South 80. |
| Mean Revenue | Pass · 4,751 ms | Answer contained 100 and successful calculation evidence. |
| Preview and approved column change | Pass · 10 ms preview | Profit stayed absent before approval. Saved values were 60, 30, 20, blank, and 40. |
| Direct restricted calculations | 4 / 4 | Row count, total, mean, and missing-value count matched fixture references. |
| Restricted-operation rejection | 5 / 5 | Imports, file access, eval, direct column assignment, and in-place mutation were rejected. |

The numerical answer grader checks expected number presence plus execution and
citation events. It does not exhaustively validate every sentence or table label.
The chart check verifies a downloadable SVG artifact.

### Company assistance

| Case | Automatic result | Latency |
| --- | --- | --- |
| Annual leave fact and citation | Pass | 3,046 ms |
| Grove price fact and citation | Pass | 2,747 ms |
| Password length fact and citation | Pass | 3,206 ms |
| General question with no company citation | Pass | 2,924 ms |
| Workbook request handed to Data Analysis Agent | Pass | 4 ms |
| Prompt-injection request blocked | Pass | 4 ms |
| Unsupported company policy | Grader false negative | 6,498 ms |
| **Automatic total** | **6 / 7** | One response per case |

For the last case, the answer correctly said it **could not find** the requested
policy. The literal abstention matcher did not recognize that phrasing. The raw
failed check is retained for inspection. Its displayed 0.71 confidence came from
retrieval, which illustrates why that score cannot establish answer correctness.

### Document OCR and extraction

| Evaluation | Result | Scope |
| --- | --- | --- |
| End-to-end pipeline | Completed · 26,057 ms | Two-page PDF through upload, segmentation, OCR, classification, extraction, review, and export. |
| Document classification | 2 / 2 | One synthetic PAN page and one benefit-illustration form. |
| Field exact match | 8 / 8 | Case and whitespace normalized before comparison. |
| Mean field character error rate | 0.000 | Edit distance divided by reference length, averaged over eight fields. |
| Raw OCR character error rate | 0.000 | Separate recognition request on the first page, with case and whitespace normalized. |
| Export availability | 4 / 4 HTTP 200 | Documents JSON, review JSON, Excel, and evaluation JSON. |
| Azure OCR | Failed | The configured endpoint could not be resolved by DNS. |
| Google Document AI | Failed | The configured project rejected the request with billing disabled. |
| Vision-model fallback | Passed | Handled both pipeline pages and the separate raw OCR check. |
| Handwritten and degraded-scan accuracy | Unmeasured | Live fixtures contained clear printed text. |

## Parameter choices and sensitivity checks

The application uses pretrained services. No model weights were fine-tuned, and
no temperature search was performed. The following values are runtime choices.

| Setting | Current value | Reason and evidence |
| --- | --- | --- |
| Analyst temperature | 0.1 | Low sampling variability for tool-based calculations. No comparative sweep performed. |
| Assistance temperature | 0.0 | Consistent source-based responses. No comparative sweep performed. |
| LangChain timeout / retries | 90 seconds / 1 retry | Bound model-call waits and transient retry attempts. These are call-level limits. |
| Analyst tool budget | 5 rounds | Bound repeated tool use within one question. |
| Analysis worker | 5 seconds, 20,000 output characters | Bound execution and returned output. |
| Retrieval chunk size / overlap | 1,200 / 180 characters | Bounded source context with overlap across chunk boundaries. |
| Retrieval result limit | 5 chunks | Preserve multiple relevant source sections. |
| Retrieval acceptance | 0.15 combined score | Uses token cosine and optional vector scores. Vector-only candidates require 0.55. These scores are ranking heuristics. |
| Field review threshold | 0.85 | Conservative review policy for extracted values. No labeled production calibration. |
| Handwriting penalty | 0.20 | Subtracted from model confidence for handwritten fields. Live handwriting validation remains open. |
| PDF raster scale | 1.5× | Current render setting. Resolution alternatives were not benchmarked. |

| Sensitivity experiment | Values checked | Measured result | Decision |
| --- | --- | --- | --- |
| Retrieval top-k | 1, 3, 5 | Hit rate 3 / 3 and MRR 1.000 at each k | Keep k = 5. Three straightforward questions do not justify changing it. |
| Field acceptance threshold | 0.75, 0.85, 0.95 | All eight printed fields accepted at each threshold | Keep 0.85. This sample cannot distinguish the settings or quantify false acceptance. |

The threshold experiment replays saved field scores without additional model
calls. It measures acceptance sensitivity, rather than a new extraction run.

## Reproduce the checks

```bash
source .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd backend
pytest -q
python -m evals.run_all_evaluations
python -m evals.run_all_evaluations --live
```

The default evaluation runs local sandbox and retrieval checks. `--live` also
requires the backend on port 8000 and sends generated fixtures and reference
questions to configured services. Live tests use new session UUIDs and remove
their workbook sessions afterward. OCR output jobs remain available for inspection.
Chroma may download its default embedding model on first use.

Run the frontend checks from a separate terminal at the repository root.

```bash
cd frontend
npm test
npm run build
```

The final regression run passed **134 backend tests and 3 subtests**. The
frontend suite passed **7 tests**, and the production build succeeded.

## Storage and current limits

Workbook files, versions, chart metadata, and OCR job outputs are local to the
backend. Workbook and answer state also use browser storage scoped to a session.
Conversation checkpoints, pending previews, and the company evidence index are
process-local. A backend restart invalidates pending approvals.

The application currently uses session UUIDs without authenticated user or
tenant accounts. The expression interpreter restricts supported operations and
uses a child process, while sharing the backend host's operating-system context.
The current evaluation covers clear synthetic inputs and selected adversarial
requests. Larger held-out datasets, noisy scans, handwriting, concurrency, and
confidence calibration need separate validation.

## Repository layout

```text
backend/
  main.py                    FastAPI application and frontend serving
  excel_agent/               Workbook analysis, restricted execution, mutations
  document_assistance/       Company knowledge retrieval and general assistance
  document_intelligence/     OCR, extraction, validation, and exports
  datapilot/                 Shared providers, configuration, guardrails, latency
  evals/                     Reproducible runner and measured results
  tests/                     Backend regression tests
frontend/src/                Vue screens, components, API client, design tokens
docs/                        Architecture, pipelines, evaluation methods
```
