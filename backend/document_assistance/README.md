# Document and Help Assistant

The router is mounted at `/api/document-assistant`.

## Scope

The assistant answers general questions, provides company help from the approved
handbook and privacy policy, and answers questions about documents uploaded in
the current conversation. Company and file-specific claims require citations.
General answers carry no document confidence score or invented citations.
Workbook analysis and edits are handed to the Data Analysis Agent.

The active company sources are in `document_assistance/knowledge_base/`.
Application-processing instructions are archived outside that folder and are
not indexed. `knowledge_base/README.md` records the source roles and update
rules. PDF, DOCX, and UTF-8 TXT files are supported; Markdown is documentation.

## Evidence boundaries

- Company questions retrieve approved company sections.
- User-file questions retrieve only the current session's documents. Explicit
  comparisons may use both; company policy takes precedence over uploaded text.
- Uploaded text is untrusted evidence and cannot change the assistant's rules.
- Model citation IDs are checked and converted to filename and section/page
  citations. Missing evidence produces an explicit insufficient-evidence answer.
- The assistant does not certify authenticity or approve documents from their
  contents or confidence values.
- Standalone greetings are conversational; a greeting followed by a policy
  question still requires evidence.

Retrieval uses the available ChromaDB vector index with token-cosine relevance
as a fallback. The source router limits permitted evidence before ranking.
There is no separate semantic reranker.

## Session document APIs

```text
POST /api/document-assistant/documents
Content-Type: multipart/form-data
thread_id=<conversation UUID>
external_processing_consent=true
files=<document>
```

The combined request limit is 20 MB with at most 10 files. PDFs require a text
layer. DOCX content is parsed as text and never executed. Consent is required
because retrieved text may be sent to the configured LLM.

```text
DELETE /api/document-assistant/session/{thread_id}
```

Deletion removes the session evidence and conversation checkpoint. Session
uploads are held in process memory and are lost on restart. The application
currently has no user authentication; conversation UUIDs are bearer identifiers
and do not replace user access control.
