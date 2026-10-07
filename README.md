# DataPilot

## Project structure

- `excel_agent/` - Excel loading, data analysis, and web-search tools.
- `document_assistance/` - Multi-turn, document-grounded support assistant.
  - `core/` - Conversation and retrieval logic.
  - `knowledge_base/` - Source documents for the assistant.
  - `schemas/` - Response and citation models.
- `document_intelligence/` - Document classification and field extraction.
  - `core/` - Processing and human-review logic.
  - `input/` - Documents to process.
  - `output/` - Structured extraction results and review reports.
  - `schemas/` - Document types and extraction field definitions.
- `ui/` - Chat interface shared by the assistants.
- `tests/` - Feature-specific tests and fixtures.

The feature packages are kept separate so each can be developed and tested
independently. The shared chat interface and assistant implementations are
scaffolding areas; the existing Excel agent remains under `excel_agent/`.