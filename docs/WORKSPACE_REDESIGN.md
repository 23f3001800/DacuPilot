# Workspace redesign

The redesign gives InsightPilot three primary destinations, Workspace, Results,
and Documents. Settings remain in the header, and Company Help opens from a
small assistant button. The workbook and the Data Analysis Agent share one
workspace so users can inspect the source while asking questions and approving
changes.

## Requirements and acceptance criteria

- Upload, inspect, refresh, download, and delete an actual saved workbook.
- Preserve the workbook and conversation when navigating between destinations.
- Show streamed activity and a live orange latency counter beside the response.
- Require visible processing consent before external AI analysis.
- Preview column changes, wait for approval, then refresh the sheet and show the
  applied column. Support canceling a preview and restoring prior versions.
- Show only generated charts and saved answers from the current workspace.
- Keep company help and document extraction distinct from workbook analysis.
- Provide useful empty, loading, error, offline, and completed states.
- Support keyboard operation, readable focus states, and narrow screens.
- Serve the same Vue application in development and from the backend build.

## Design and architecture

Replace the accumulated stylesheet with one token system for typography,
spacing, color, controls, panels, and states. Use reusable icons, safe Markdown
answers, answer metadata, confirmation dialogs, and the Company Help panel.
Keep workbook analysis mounted during navigation. Read chart artifacts from the
server and saved answers from storage scoped to the workbook session.

The former Overview, Analysis, Dashboards, Reports, and Workflows navigation
items are consolidated into Workspace and Results. Workbook profiling runs
inside the workspace's data-quality view.

## Dependency decisions

Marked formats streamed answers as readable paragraphs, lists, tables, and code.
DOMPurify sanitizes the generated HTML before rendering. Remote images and
active HTML are excluded. Marked 15 is pinned to support the existing Node 18
environment. No component framework or chart demo data is added.

## Verification

Verified on November 6, 2026.

- Backend regression suite passed with 132 tests and 3 subtests.
- Frontend stream and request suite passed with 7 tests.
- The production build completed with Vite 6.4.5 and Node 18.19.1.
- Browser validation used a synthetic five-row workbook with one missing cost.
  Upload, visible consent, navigation persistence, refresh, and download worked.
- Adding Profit produced an approval preview while the sheet retained four
  columns. Approval saved a five-column workbook with values 60, 30, 20, blank,
  and 40. The applied column was highlighted in the sheet.
- A real model request returned regional revenue totals of North 200, West 120,
  East 100, and South 80. The generated chart matched those totals. The answer
  displayed 8,345 ms latency, a source, and an 83% heuristic evidence score.
- The first generic chart request failed when the model assigned a column on a
  temporary summary. The sandbox rejected that unsupported operation. Updated
  instructions produced a supported group-by expression in the live diagnostic.
  Streamed tool outcomes now distinguish failed calculations from chart output.
- Company Help answered a general spreadsheet question through its separate API.
- The deletion confirmation opened and canceled without changing the workbook.
- Refreshing the browser restored the saved workbook, chat, charts, and consent.
- The profile workflow completed all four stages in 76 ms. Its output reported
  five rows, five fields, two missing cells, and three generated charts.
- Results labels a successful chart with a failed calculation as a partial
  outcome. This preserves the calculation failure alongside the usable chart.
- Desktop 1280 by 800 and narrow 390 by 844 layouts were visually reviewed.
- The backend returned HTTP 200 for the Vue entry page, favicon, and modified
  workbook download.

The document extraction screen was reviewed in its empty state. A new live OCR
extraction was not run during this redesign verification. Existing automated
document-processing checks passed as part of the backend suite.
