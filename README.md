# DataPilot

## Project structure

```text
excel_agent/
  agent.py       Agent graph, data tools, and model configuration
  api.py         FastAPI routes and SSE response formatting
  main.py        API server entry point
  loader.py      Excel parsing and schema discovery
  engine.py      DataFrame code execution wrapper
  *.xlsx         Sample inventory workbook
document_assistance/
  core/
    document.py  Multi-turn conversation graph
    loader.py    DOCX knowledge reader and optional PDF vector ingestion
  knowledge_base/
    Questions.docx  Assignment requirements, loaded with section citations
  schemas/        Empty schema package
document_intelligence/
  core/           Staged evaluation processor
  schemas/        Typed extraction fields and confidence/review metadata
  utils/          OCR request and text evaluation helpers
  input/          Empty; provided sample scans remain under data/Question3
  output/         Empty output location
ui/
  index.html      Responsive inventory chat interface
tests/
  excel_agent/
  document_assistance/
  document_intelligence/
data/Question3/   Provided identity and insurance documents
```

Keep each feature isolated in its package. Excel agent orchestration, HTTP
transport, and process startup are separate within `excel_agent`. The document
assistant loads and cites sections from `Questions.docx`; optional PDF vector
ingestion remains separate from the conversation graph.

Run the offline tests from the repository root with:

```bash
python -m unittest discover -s tests -t . -v
```

Run the Excel API and chat UI with `python -m excel_agent.main`, then open
`http://localhost:8000`. It requires `GEMINI_API_KEY`; web-search tool calls
additionally require `TAVILY_API_KEY`. The UI keeps a per-browser conversation
ID and starts a fresh isolated thread with **New chat**.

`python -m document_intelligence.main` currently runs a synthetic benchmark,
not OCR/classification of the files in `data/Question3`. OCR request formatting,
schemas, confidence thresholds, and manual-review routing are unit-tested offline.
Actual classification and structured extraction for all documents remain
incomplete. Do not submit identity or financial scans to an external model
without explicit approval.