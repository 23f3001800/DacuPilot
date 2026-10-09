# DocuPilot

DocuPilot is an enterprise web application for spreadsheet analysis, evidence-based document
support, and document data extraction. It uses one FastAPI server, a shared
Gemini/Azure OpenAI-compatible model configuration, and a single browser UI.

## 1. Problem Statement

Enterprises struggle with fragmented data silos and hallucination risks:
- Querying complex spreadsheet workbooks requires manual Python scripts or fragile formulas.
- Answering compliance and policy questions often leads to ungrounded claims lacking verified source page/section citations.
- Ingesting identity and insurance documents involves mixed-quality scans and variable handwriting requiring automated classification, OCR failover, and strict confidence thresholding to prevent erroneous downstream processing.

## 2. Solution Overview

DocuPilot unites these capabilities into a single auditable platform:
1. **Spreadsheet Data Agent**: Sandboxed Pandas REPL execution over active workbooks with real-time SSE streaming.
2. **Document-Aware Support Assistant**: Multi-turn conversational retrieval grounded in an authoritative application knowledge base (PDF) and session documents with strict citation validation (`Source: [doc — section/page]`).
3. **Document Intelligence Pipeline**: Multi-page segmentation, dual OCR hierarchy (Azure DI → Google DocAI → Vision LLM), 10 document schemas, and an 85% confidence shield with a 0.20 handwriting penalty routing uncertain fields to human review.

## 3. Architecture

![DocuPilot platform architecture](docs/images/platform-architecture.svg)

## 4. Three Core Modules

### 4.1 Spreadsheet Data Agent

Upload an `.xlsx` or `.xlsm` workbook and ask questions about its data. The
agent uses a LangGraph workflow to reason over the active workbook, run
Pandas-backed analysis, and optionally search the web with Tavily. Replies are
streamed to the browser using server-sent events. Uploading another workbook
replaces the active dataset for the application.

![Spreadsheet Data Agent request and streaming flow](docs/images/spreadsheet-agent.svg)

### 4.2 Document Assistant

Ask questions about application knowledge or consented session documents. The
assistant ingests authoritative policy documents (`application_knowledge_base.pdf` covering
Privacy Policy, Verification Policy, Document Definitions, Confidence Policy, Human Review Policy,
and Application Guidelines, as well as `privacy_policy.pdf`), indexes chunks into ChromaDB
with dense vector embeddings and metadata (`document`, `section`, `page`, `chunk_id`), and
executes pure semantic vector search with cosine similarity. Answers cite verified sources
(`Source: [file — section/page]`) and enforce strict grounding boundaries. Uploaded documents
are isolated by conversation UUID, held in process memory, and removed when the session is deleted
or the app restarts.

```text
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              DOCUMENT ASSISTANT ARCHITECTURE                            │
└─────────────────────────────────────────────────────────────────────────────────────────┘

 1. KNOWLEDGE SOURCES & INGESTION
 ┌────────────────────────────────────────┐       ┌──────────────────────────────────────┐
 │    Application Knowledge Base PDF      │       │        Session User Uploads          │
 │  • application_knowledge_base.pdf (6p) │       │  • PDF / DOCX / TXT                  │
 │  • privacy_policy.pdf                  │       │  • Thread-scoped in-memory store     │
 │  • 34 Chunks pre-indexed at startup    │       │  • Zero execution / sandboxed        │
 └───────────────────┬────────────────────┘       └──────────────────┬───────────────────┘
                     │                                               │
                     └───────────────────────┬───────────────────────┘
                                             ▼
 2. VECTOR STORAGE & RETRIEVAL
 ┌───────────────────────────────────────────────────────────────────────────────────────┐
 │                                ChromaDB Vector Store                                  │
 │  • Pure semantic similarity search (Cosine Space, HNSW index)                         │
 │  • Rejection threshold: Cosine similarity >= 0.55 filters out-of-domain noise         │
 │  • Zero BM25 / Zero CrossEncoder overhead -> sub-300ms retrieval                      │
 └───────────────────────────────────────────▲───────────────────────────────────────────┘
                                             │ [Semantic Query]
 3. QUERY PROCESSING & DIALOGUE              │
 ┌───────────────────────────────────────────┴───────────────────────────────────────────┐
 │                       User Input / Conversational Query                               │
 └───────┬───────────────────────────────────────────────────────────────────────────────┘
         │
         ├───► [Greeting Fast-Path: "hello", "hi", "help"] ──► Returns suggested prompts (<1ms)
         │
         ▼
 ┌───────────────────────────────────────────────────────────────────────────────────────┐
 │                           Dynamic Query Optimizer                                     │
 │  • Conversational noise stripping ("Can you tell me...")                              │
 │  • Coreference resolution ("it", "that policy", "rules for it")                       │
 │  • Multi-turn dialogue history tracking without topic contamination                   │
 └───────────────────────────────────────────┬───────────────────────────────────────────┘
                                             ▼
 4. GROUNDED GENERATION & CITATION VALIDATION
 ┌───────────────────────────────────────────────────────────────────────────────────────┐
 │                               Multi-Provider LLM                                      │
 │  • OpenAI / Google Gemini / Azure OpenAI                                              │
 │  • Strict evidence constraint: answer strictly from retrieved chunks [E1]..[E5]       │
 │  • Anti-override prompt injection shield & boundary isolation                         │
 └───────────────────────────────────────────┬───────────────────────────────────────────┘
                                             ▼
 ┌───────────────────────────────────────────────────────────────────────────────────────┐
 │                           Citation & Safety Validator                                 │
 │  • Validates and converts [E1] -> Source: [application_knowledge_base.pdf — Page X]   │
 │  • Strips ungrounded claims; returns zero-hallucination refusal if evidence missing   │
 └───────────────────────────────────────────┬───────────────────────────────────────────┘
                                             ▼
 5. STREAMING DELIVERY & REAL-TIME TELEMETRY
 ┌───────────────────────────────────────────────────────────────────────────────────────┐
 │                                UI & SSE Stream Protocol                               │
 │  • Server-Sent Events (SSE) token streaming to frontend                               │
 │  • ⚡ Vibrant Red Latency Badge (#dc2626) updated live every 80ms                     │
 │  • 🎯 Retrieval Confidence Badge (0-100%) + Expandable Rationale                      │
 └───────────────────────────────────────────────────────────────────────────────────────┘
```

- **Knowledge Base Ingestion & ChromaDB**: PyMuPDF-based text and layout extraction, section detection, and in-memory ChromaDB cosine vector indexing with document, section, page, and chunk_id metadata (34 pre-indexed chunks at startup).
- **Pure Semantic Vector Retrieval**: Employs direct ChromaDB cosine similarity search over pre-indexed document chunks with a similarity rejection threshold ($\ge 0.55$) to filter out-of-domain queries with low latency (zero BM25/CrossEncoder overhead).
- **Conversational Greeting Fast-Path**: Intercepts greetings (`"hello"`, `"hi"`) in <1ms, offering suggested starting questions without triggering unnecessary retrieval.
- **Domain-Agnostic Query Optimization**: Self-learning topic and entity indexation without hardcoded domain keywords. Dynamically resolves conversational coreferences ("it", "that document", "the previous one", "his age") and isolates clean topic switches to completely prevent cross-topic retrieval contamination.
- **Citation & Grounding Validator**: Translates internal evidence markers `[E1]` into explicit, verifiable citations (`Source: [file — section/page]`). Strips ungrounded claims, and explicitly reports insufficient evidence when information is missing from permitted sources.
- **Evaluation & Latency Telemetry**: Computes retrieval confidence scores and multi-stage latencies, rendering interactive badges in the frontend chat UI (vibrant red `#dc2626` latency badge) and streaming detailed telemetry to the browser console.
- **Session Cache**: In-memory thread-safe LRU cache providing sub-millisecond responses on repeated queries within the same document session.

Supported user uploads are PDF, DOCX, and UTF-8 TXT. PDFs must contain a text
layer; this feature does not perform OCR.

### 4.3 Document Intelligence

Upload PDFs or images to extract structured fields from identity, insurance,
and related documents. The pipeline segments documents into pages, runs an
enterprise OCR hierarchy, and leverages the configured LLM for classification and
field extraction. Confidence scoring and validation flag results for human
review. JSON, review-report, and Excel files are available for download.

- **Dual OCR Hierarchy**: Uses **Azure Document Intelligence as Primary OCR** for table and key-value extraction, with automatic failover to **Google Cloud Document AI as Secondary OCR**, and Vision LLM as tertiary fallback.
- **Confidence Shield**: Fields scoring below the 85% threshold or containing handwritten entries receive confidence penalties and are routed for human review.

Processing requires explicit consent before pages are sent to configured
external OCR and AI providers. Extracted information is not independently
verified and must be reviewed before use.

![Document Intelligence processing flow](docs/images/document-processing.svg)

## 5. Technology Choices

| Layer / Component | Technology | Rationale |
| :--- | :--- | :--- |
| **Backend Framework** | FastAPI (Python 3.12) | High-concurrency async I/O, native Server-Sent Events (SSE) streaming, OpenAPI autodocs. |
| **Document Ingestion** | PyMuPDF (`fitz`) | High-speed text and layout extraction from PDF binaries without external C++ or Java dependencies. |
| **Vector Database** | ChromaDB (`chromadb`) | In-memory semantic vector store with native cosine distance space, metadata filtering, and zero cloud lock-in. |
| **Agent Orchestration** | LangGraph / LangChain | Explicit graph state machines, streaming event hooks (`astream_events`), and deterministic evaluation nodes. |
| **Primary OCR** | Azure Document Intelligence | High-fidelity table and layout extraction with word-level bounding boxes. |
| **Secondary OCR** | Google Cloud Document AI | Enterprise-grade document OCR providing automatic failover if Azure is unreachable. |
| **Data Extraction** | Pydantic V2 | Strict type validation, regex pattern matching, and automated field-level scoring matrices. |
| **Frontend** | HTML5 / CSS3 / Vanilla JS | Zero build step, lightweight, low latency, real-time live streaming timer in red (`#dc2626`). |

## 6. How to Run

### Quick start

Use Python 3.12 and run these commands from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Create a `.env` file in the repository root. For Gemini, start with:

```dotenv
AI_PRIMARY_PROVIDER=gemini
GEMINI_API_KEY=replace-with-your-api-key
GEMINI_MODEL=gemini-3.6-flash
```

Set the required values for your chosen provider and services, then start the server:

```bash
python main.py
```

Open [http://localhost:8000](http://localhost:8000).

On Windows PowerShell, activate the environment with:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Configuration

### Language model provider

Choose OpenAI, Gemini, or Azure OpenAI-compatible service with
`AI_PRIMARY_PROVIDER=openai`, `AI_PRIMARY_PROVIDER=gemini`, or `AI_PRIMARY_PROVIDER=azure`. The legacy
`TRACEROOT_PROVIDER` setting is accepted if `AI_PRIMARY_PROVIDER` is unset.

| Provider | Environment variables | Description |
| --- | --- | --- |
| OpenAI / Custom Endpoint | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` | Official OpenAI or any OpenAI-compatible API (Ollama, vLLM, Groq, DeepSeek). Default base URL is `https://api.openai.com/v1`. |
| Gemini | `GEMINI_API_KEY`, optional `GEMINI_MODEL` | Google Gemini 3.6 Flash / Pro via OpenAI-compatible endpoint. |
| Azure OpenAI | `AZURE_OPENAI_BASE_URL`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_MODEL` | Azure OpenAI resource endpoint or custom deployment. |
| Azure AI Foundry aliases | `AZURE_FOUNDRY_ENDPOINT`, `AZURE_FOUNDRY_API_KEY`, `AZURE_FOUNDRY_MODEL` | Foundry hub and project endpoints. |

Azure CLI authentication is also supported. Set
`AZURE_OPENAI_AUTH_MODE=azure-cli`, configure the Azure endpoint and model, and
sign in with `az login` in the environment running the application. The signed
in identity must have permission to invoke the Azure OpenAI resource. API-key
authentication is the default.

### Enterprise OCR Services

DocuPilot implements a resilient dual-OCR hierarchy with automatic cascading failover:

| OCR Role | Provider | Environment variables | Purpose |
| --- | --- | --- | --- |
| **Primary OCR** | Azure Document Intelligence | `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT`, `AZURE_DOCUMENT_INTELLIGENCE_KEY` | High-fidelity table and layout extraction with word-level bounding boxes. |
| **Secondary OCR** | Google Cloud Document AI | `GCP_PROJECT_ID`, `GCP_LOCATION`, `DOCAI_PROCESSOR_ID`, `GOOGLE_APPLICATION_CREDENTIALS` | Automatic failover for enterprise document parsing and OCR. |
| **Fallback OCR** | Multimodal Vision LLM | Shared AI Provider (`OPENAI_API_KEY`, `GEMINI_API_KEY`, or Azure) | Zero-dependency direct image classification and field extraction. |

### Other services & thresholds

| Feature | Environment variables | Default |
| --- | --- | --- |
| Web search | `TAVILY_API_KEY` | None |
| Workbook override | `EXCEL_FILE_PATH` | None |
| Field confidence shield | `FIELD_CONFIDENCE_THRESHOLD` | `0.85` |
| Handwriting penalty | `HANDWRITTEN_CONFIDENCE_PENALTY` | `0.20` |

Keep API keys and service-account files private. Do not commit `.env` or
credential files.

## Security & Prompt Injection Guardrails

DocuPilot includes defense-in-depth security guardrails (`datapilot/guardrails.py`):
- **Input Sanitization & Injection Detection**: Scans user queries and retrieved evidence for instruction override attacks (e.g., `ignore previous instructions`), developer mode jailbreaks (DAN), and prompt extraction attempts.
- **Delimiter Breakout Protection**: Strips structural delimiters (`</retrieved_evidence>`, `<system>`) from untrusted documents and user queries to prevent context escapes.
- **Hardened Agent Prompts**: Both Document Assistant and Spreadsheet Data Agent are injected with strict non-overridable boundary constraints.
- **Execution Sandbox Safeguards**: The Spreadsheet Data Agent engine restricts dynamic Python code execution, explicitly forbidding dangerous operating system calls (`os`, `sys`, `subprocess`, `open`, `eval`).

## API routes

| Route | Purpose |
| --- | --- |
| `GET /api/health` | Server health |
| `GET /api/data/schema` | Active workbook schema |
| `POST /api/data/upload` | Upload an Excel workbook |
| `POST /api/chat/stream` | Stream Data Agent replies with tool execution and latency (SSE) |
| `POST /api/document-assistant/chat` | Ask the Document Assistant (synchronous) |
| `POST /api/document-assistant/chat/stream` | Stream Document Assistant replies with citations and step updates (SSE) |
| `POST /api/document-assistant/documents` | Add session-scoped evidence |
| `DELETE /api/document-assistant/session/{thread_id}` | Remove session evidence and conversation |
| `GET /api/documents/settings` | Report active AI providers, models, endpoints, and safety thresholds |
| `POST /api/documents/process` | Process consented PDF/image uploads (synchronous) |
| `POST /api/documents/process/stream` | Stream real-time progress events and results for consented uploads (SSE) |
| `GET /api/documents/{job_id}/{filename}` | Download job artifacts (`documents.json`, `review_report.json`, `documents.xlsx`) |
| `GET /api/documents/{job_id}/evaluation.json` | Job evaluation matrices (`quality`, `routing`, `throughput`) |

The application supports pure **OpenAI** (with custom base URLs like Ollama, vLLM, DeepSeek, or Groq), **Google Gemini**, and **Azure OpenAI**. See `.env.example` for all configuration variables.

The application does not currently provide user authentication. Treat
conversation IDs as identifiers, not as access control.

## 7. Example Usage

### 7.1 Spreadsheet Data Agent
- **Sample Query**: `"Which product category has the highest total inventory value?"`
- **Execution**: Agent executes `df.groupby('Category')['TotalValue'].sum().idxmax()` in the sandboxed Pandas REPL.
- **Output**: Returns category details, instant red latency badge (`⚡ Latency: 450 ms`), confidence score (`🎯 Confidence: 95%`), and expandable evaluation rationale.

### 7.2 Document Assistant
- **Conversational Greeting & Suggested Questions**:
  - **User**: `"hello"`
  - **Response** (<1ms sub-millisecond fast path):
    > *"Hello! I am DocuPilot's Document Assistant. I can help answer your questions grounded in the company handbook and application policies.*
    >
    > *Here are a couple of questions you can ask me:*
    > *• What happens when confidence is low?*
    > *• What is the privacy policy regarding user data and retention?*"
- **Sample Query**: `"What happens when confidence is low?"`
- **Retrieval**: ChromaDB semantic vector search retrieves `Confidence Policy, Page 4` and `Human Review Policy, Page 5` from `application_knowledge_base.pdf`.
- **Response**:
  > *"If any field's extraction confidence falls below the 0.85 threshold, automated processing is suspended and the document is routed for human review with status HUMAN_REVIEWS_REQUIRED."*
  > **Source: [application_knowledge_base.pdf — Confidence Policy, Page 4]**

### 7.3 Document Intelligence
- **Upload**: `ECS.jpeg` (NACH Mandate containing handwritten account and bank details).
- **Processing**: Classifies as `NACH_MANDATE`, applies the 0.20 handwriting penalty (`0.90 - 0.20 = 0.70 < 0.85`), flags field in `review_report.json`, and generates downloadable Excel and JSON reports.

## 8. Evaluation & Results

### 8.1 Assignment Evidence Package

| Requirement | Implementation | Test Performed | Result | Known Limitation |
| :--- | :--- | :--- | :--- | :--- |
| **Excel Agent Answers & Code Execution** | LangGraph agent with `PythonSandboxREPL` executing Pandas queries in-memory. | `tests/excel_agent/test_engine.py` | Accurate statistical answers + code stdout in <50ms. | Complex VBA macros (`.xlsm`) are not executed. |
| **Excel Fast Latency** | Deterministic metric computation in `data_evaluation_node` replacing slow secondary LLM. | Live SSE streaming on `/api/chat/stream`. | Telemetry displays in <1s (reduced from 40s blocking delay). | Evaluates coverage and statistical sanity deterministically. |
| **Knowledge Base in PDF** | Authoritative 6-page PDF with PyMuPDF extraction in `knowledge_base/`. | `tests/document_assistance/test_application_knowledge_base.py` | Ingests all 6 policies (`Privacy`, `Verification`, `Definitions`, `Confidence`, `Human Review`, `Guidelines`). | Requires text-layer PDFs; scanned image PDFs need Document Intelligence. |
| **ChromaDB Semantic Retrieval** | ChromaDB cosine vector index with document, section, page, and chunk_id metadata. | Query: *"What happens when confidence is low?"* | Retrieves `Confidence Policy, Page 4` and `Human Review Policy, Page 5` (score ~0.70). | In-memory ChromaDB index resets on server process restart. |
| **Multi-Turn Context & Reference Resolution** | Contextual query optimizer resolving "it", "that document", "the previous one". | `tests/test_multiturn_demonstration.py` (12 turns) | Resolves coreferences across 10+ turns without topic bleeding. | Memory summary window tracks the most recent 8 turns. |
| **Citation & Grounding Validation** | `_validate_citations()` converts `[E1]` to explicit `Source: [file — section/page]`. | `test_document_assistant_end_to_end_grounded_answer_with_citations` | Returns verified citations; strips ungrounded statements. | Strict grounding refuses out-of-scope general trivia questions. |
| **Dual OCR Hierarchy & Failover** | Cascading router: Azure DI → Google DocAI → Multimodal Vision LLM. | `tests/document_intelligence/test_ocr.py` | Gracefully falls back when primary OCR endpoints are unreachable. | Cloud OCR endpoints require credentials configured in `.env`. |
| **Handwritten Field Penalty & Review** | 0.85 threshold; handwritten fields receive 0.20 penalty -> `HUMAN_REVIEWS_REQUIRED`. | `tests/document_intelligence/test_pipeline.py` | Raw 0.90 - 0.20 = 0.70 < 0.85 -> correctly routes to human review ledger. | Highly distorted cursive text may require manual human transcription. |
| **Document Artifact Exports** | Structured extraction exports `documents.json`, `review_report.json`, and `documents.xlsx`. | `tests/document_intelligence/test_pipeline.py` | Generates audit-ready JSON and color-coded Excel review workbook. | Output files stored locally in session directories. |

### 8.2 Telemetry & Evaluation Framework (Measured Benchmark Scores)

DocuPilot executes quantitative evaluation benchmarks across all three modules (`evals/run_all_evaluations.py`):

#### 1. Document Intelligence Evaluation Matrix

| Metric Dimension | Target Metric | Measured Score | Benchmark Condition / Asset |
| :--- | :--- | :--- | :--- |
| **Pipeline Quality** | Mean Classification Confidence | **95.33%** | Evaluated on PAN Card & Aadhaar datasets (Min: 92.0%, Max: 99.0%) |
| | Field Extraction Confidence | **90.20%** | Printed text: 99.0%; Handwritten after 0.20 penalty: 70.0% |
| | Schema Validation Pass Rate | **66.67%** | Clean printed forms pass; format failures and low confidence routed |
| **Stage Gates & CER** | Classification Stage Gate | **Passed (94.0%)** | Anchors identify target form layout accurately |
| | OCR Layout Gate & CER | **Passed (CER: 0.1895)** | Text recovery Character Error Rate on clean and scanned forms |
| | Field Business Gate & CER | **Flagged (CER: 0.2874)** | Cursive handwritten signature mismatch routed to manual review |
| | Overall Routing Decision | **`HUMAN_REVIEWS_REQUIRED`** | Safety threshold 0.85 shield correctly prevents unverified writes |
| **Pipeline Throughput** | Total Multi-Page Duration | **450.06 ms** | End-to-end multi-page execution |
| | Average Per-Page Latency | **150.02 ms** | Segmentation + OCR + Schema Extraction + Routing |
| | Pipeline Processing Speed | **6.67 pages / sec** | High-throughput batch streaming capability |
| **Routing Decision** | Automated Straight-Through | **33.33%** | High-confidence error-free documents |
| | Human Review Queue Rate | **66.67%** | Low-confidence and handwritten fields intercepted |

#### 2. Spreadsheet Data Agent Evaluation Matrix

| Metric Dimension | Target Metric | Measured Score | Benchmark Condition / Asset |
| :--- | :--- | :--- | :--- |
| **Execution Accuracy** | Code Execution Pass Rate | **100% (5/5)** | Evaluated on real dataset (`5590bea463a8475985747bc35f3fc11e.xlsx`, **73,316 rows**) |
| | Mean REPL Latency | **1.03 ms** | Sandboxed in-memory Pandas execution across 73k rows |
| **Security Sandbox** | OS / Shell Attack Block Rate | **100% (5/5)** | Blocked: `os.system`, `subprocess.Popen`, `open()`, `sys.exit`, `eval()` |
| **Input Guardrails** | Uninitialized Input Guardrail | **100% Intercept** | Returns immediate user guidance (`Workbook Required`) in **1.0 ms** |
| **Agent Confidence** | Statistical Reflection Score | **96% (0.96)** | Deterministic evaluation node verification |
| | Dataset Coverage Metric | **100.0%** | Comprehensive record and column analytical coverage |

#### 3. Document Assistant Evaluation Matrix

| Metric Dimension | Target Metric | Measured Score | Benchmark Condition / Asset |
| :--- | :--- | :--- | :--- |
| **Semantic Retrieval** | In-Scope Query Hit Rate @ 5 | **100.0%** | ChromaDB cosine similarity against 34 indexed knowledge chunks |
| | Mean Reciprocal Rank (MRR) | **0.80 – 1.00** | Top hit for low confidence maps to `Confidence Policy, Page 4` (score: 0.704) |
| | Average Cosine Similarity | **0.75 – 0.80** | Privacy: `0.797`, Verification: `0.776`, Confidence: `0.758` |
| | Semantic Query Latency | **262.38 ms** | Pure vector distance calculation (zero BM25 / zero CrossEncoder delay) |
| **Grounding & Safety** | Citation Grounding Coverage | **100.0%** | Every assertion verified with `Source: [file — section, Page X]` |
| | Out-of-Scope Refusal Rate | **100.0%** | Rejects general trivia questions without hallucination |
| **Fast-Path Latency** | Conversational Greeting | **0.082 ms (<1 ms)** | Instant greeting reply with 2 suggested starting prompt questions |
| | Frontend Telemetry Stream | **Real-Time Live** | Live timer updates every 80 ms, styled with red badge (`#dc2626`) |

## 9. Failure Handling & Security Guardrails

DocuPilot implements defense-in-depth security guardrails and handles known enterprise failure modes:

### 9.1 Security & Injection Guardrails (`datapilot/guardrails.py`)
- **Input Sanitization & Injection Detection**: Scans user queries and retrieved evidence for instruction override attacks (e.g., `ignore previous instructions`), developer mode jailbreaks (DAN), and prompt extraction attempts.
- **Delimiter Breakout Protection**: Strips structural delimiters (`</retrieved_evidence>`, `<system>`) from untrusted documents and user queries to prevent context escapes.
- **Hardened Agent Prompts**: Both Document Assistant and Spreadsheet Data Agent are injected with strict non-overridable boundary constraints.
- **Execution Sandbox Safeguards**: The Spreadsheet Data Agent engine restricts dynamic Python code execution, explicitly forbidding dangerous operating system calls (`os`, `sys`, `subprocess`, `open`, `eval`).

### 9.2 Pipeline Verification & Observed Failure Modes

Live end-to-end verification against real test assets (`data/Question3/`) confirms how the pipeline handles edge cases, low confidence scores, and unsupported documents:

| Category | Observed Behavior / Asset | Pipeline Resolution |
| :--- | :--- | :--- |
| **Unsupported Document Type** | `Proposal Ashok.pdf` (Page 1)<br>`Assignment Ashok.pdf` (Pages 1 & 2) | Classified as `UNKNOWN`. Not present in the 10 supported schemas; logged in `review_report.json` under `flagged_fields` with reason `"Unsupported or unknown document type: UNKNOWN"` and marked for human review without failing the batch job. |
| **Handwriting Confidence Penalty** | `ECS.jpeg` (`NACH_MANDATE`) | Hand-filled fields (`bank_account_number`, `ifsc_code`, `frequency`) receive the configured handwriting penalty (0.20) and score below the 0.85 threshold; flagged in `review_report.json` and routed to `HUMAN_REVIEWS_REQUIRED`. |
| **Partial / Incomplete Form** | `Proposal Ashok.pdf` (Page 2 - `MORAL_HAZARD_QUESTIONNAIRE`) | Page-level classification confidence (0.75) is below threshold (0.85); flagged with reason `CLASSIFICATION_BELOW_CONFIDENCE_THRESHOLD`. |
| **OCR Provider Failover** | Azure DI DNS unreachable or GCP DocAI billing disabled | Automatically cascades: Azure DI → Google DocAI → Vision LLM fallback. OCR confidence is reported as unavailable or derived from fallback, with pipeline completing successfully. |

## 10. Limitations & Production Considerations

1. **OCR on Extreme Distortion**: Severely degraded historical scans or heavily skewed photos may require manual orientation adjustment before automated ingestion.
2. **Volatile Spreadsheet Formulas**: Volatile Excel functions (e.g., `=NOW()`, `=TODAY()`) and complex external workbook links require saved calculated values in the `.xlsx` file.
3. **In-Memory Concurrency**: ChromaDB and session document stores run in-memory within the active server process. Multi-worker load-balanced deployments should back ChromaDB with persistent disk or client-server mode.
4. **Text Layer Requirement for Document Assistant**: The Document Assistant is optimized for text-based document policies; scanned image PDFs must be processed via the Document Intelligence pipeline.

## Tests

Run the offline test suite from the repository root:

```bash
python -m unittest discover -s tests -t . -v
```

Tests use mocked external services and do not send local documents to model or
OCR providers.
