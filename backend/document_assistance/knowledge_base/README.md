# Document Assistant knowledge package

This folder contains approved reference material for company document and help
assistance. It is not the knowledge source for DataPilot workbook analysis,
charts, dashboards, or spreadsheet changes.

## Sources and ownership

| File | Approved use |
| --- | --- |
| `nimbus_orchard_handbook.pdf` | Company overview, handbook topics, people operations, expenses, security, and support contacts. |
| `privacy_policy.pdf` | Canonical company privacy, consent, retention, and data-handling guidance. |
| `application_knowledge_base.pdf` | Document-processing product guidance: document types, verification, extraction confidence, and human review. |

The privacy section repeated inside `application_knowledge_base.pdf` is kept in
the original source for provenance, but runtime retrieval excludes that section
so the dedicated privacy policy remains the single source of truth.

## Update rules

- Add only approved company or document-processing reference sources.
- Record the owner, review date, and intended scope when replacing or adding a
  source; avoid adding overlapping copies of an existing policy.
- Keep company policy separate from product instructions and user-uploaded
  documents. User uploads are session-scoped evidence and never become package
  sources.
- Do not add DataPilot workbook, spreadsheet UI, analytics, charting, or agent
  workflow instructions here. Those belong to the Data Analysis Agent and its
  application documentation.
- The loader indexes PDF, DOCX, and UTF-8 TXT files. This README is package
  documentation and is not indexed as assistant evidence.
