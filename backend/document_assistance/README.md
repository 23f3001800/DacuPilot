# Document Assistant

The feature router is mounted by the root application at
`/api/document-assistant`.

## Knowledge boundaries

- Application knowledge sources are loaded at startup from
  `document_assistance/knowledge_base/`. Add approved PDF, DOCX, and UTF-8 TXT
  files there; citations use their relative path and section/page.
- User uploads are indexed only in process memory and only under the supplied
  conversation UUID. They are never added to the application knowledge source.
- Application questions retrieve application sections only. Questions about a
  user's file retrieve only that session's uploads. Explicit comparisons may
  retrieve both; application knowledge is marked authoritative and takes
  precedence over uploaded evidence.
- Uploaded text is treated as untrusted evidence, never as instructions.
- Answers are limited to retrieved evidence. Citation IDs from the model are
  checked and converted to citations with the source filename and section/page.
- The assistant does not certify authenticity or make approval decisions from
  document contents or confidence values.

Retrieval currently uses a lightweight, dependency-free BM25-style keyword
ranker over overlapping text chunks. It does not yet use embeddings, ChromaDB,
or a semantic reranker. Query routing is rule-based, so ambiguous questions
default to application knowledge rather than mixing sources.

## User document APIs

Upload one or more PDF, DOCX, or UTF-8 TXT files:

```text
POST /api/document-assistant/documents
Content-Type: multipart/form-data
thread_id=<conversation UUID>
external_processing_consent=true
files=<document>
```

The combined request limit is 20 MB, with at most 10 files. PDFs must have a
text layer; scanned-page OCR is not performed by this feature. DOCX uploads
are parsed as text and are not executed. Consent is required because retrieved
text may be sent to the configured LLM when answering questions. To remove
uploaded evidence and the conversation checkpoint for a session:

```text
DELETE /api/document-assistant/session/{thread_id}
```

Session evidence is held in process memory and is lost on application restart.
The application currently has no user authentication; conversation UUIDs must
be treated as bearer identifiers, not as a replacement for access control.
