# InsightPilot frontend

Vue 3 and Vite provide one interface for development and the backend's production
build. The old legacy UI is retained as archived source and is no longer served.

## Workspace structure

- **Workspace**: an Excel-style sheet beside the Data Analysis Agent. Upload,
  refresh, save, and delete a workbook; inspect quality and history; preview and
  approve changes; run a workbook profile; review generated charts.
- **Results**: session-scoped answers, generated chart artifacts, and profile
  runs. Results can be filtered and exported as JSON; charts download as SVG.
- **Documents**: explicit-consent document processing, streamed progress, field
  review, confidence flags, downloads, and browser-local job history.
- **Preferences**: presentation settings saved in this browser.
- **Company Help**: a corner assistant for general questions and approved company
  knowledge. It uses a separate conversation and API from workbook analysis.

Workbook analysis stays mounted while navigating. Workbook IDs and consent live
in session storage; completed answers are saved under keys scoped to that ID.
The backend remains the source of truth for saved workbooks, versions, and chart
artifacts. No chart series or business metrics are hardcoded in the interface.

## Development in WSL

Start the backend from the repository root:

    cd backend
    ../.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000

In another terminal:

    cd frontend
    npm ci
    npm run dev -- --host 0.0.0.0 --port 5173 --strictPort

Open http://localhost:5173/. Vite proxies /api to the local backend.

## Verification and production build

    cd frontend
    npm test
    npm run build

The frontend tests use Node's built-in test runner and cover stream boundaries,
interrupted responses, consent, readable validation errors, and assistant
routing. The production build is written to frontend/dist. The backend serves
that index and its assets at http://localhost:8000/; a missing build produces an
actionable 503 response.

Marked 15 supports the existing Node 18 environment. DOMPurify sanitizes the
answer HTML; remote images and active HTML are excluded from rendered answers.
