# DataPilot Vue frontend

This is the parallel Vue 3 client for the existing FastAPI application.

## Development

```bash
npm install
npm run dev
```

The Vite dev server runs on port `5173` and proxies `/api` requests to
`http://localhost:8000`. The legacy frontend in `frontend/legacy-ui/ui/index.html` remains the
default FastAPI-served client until the workflows are migrated and verified.

## Migration order

1. Shared layout and health status
2. Spreadsheet upload, schema preview, and SSE chat
3. Document assistant citations and session documents
4. Document intelligence progress stream and downloads
5. Settings, error states, accessibility, and end-to-end tests

Each stage should preserve the existing API contract and receive a separate
