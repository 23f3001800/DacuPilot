# Company document and help knowledge package

The Document Assistant uses this folder for company handbook and policy answers.
It also answers ordinary general questions and questions about session uploads.
Company-specific answers require evidence from the approved company sources.

| Source | Role |
| --- | --- |
| `nimbus_orchard_handbook.pdf` | Company overview, people operations, expenses, security, products, and support contacts. |
| `privacy_policy.pdf` | Canonical company privacy, consent, retention, and data-handling guidance. |

The former application-processing guide is preserved in `../archived_sources/`
and is excluded from runtime retrieval. Its extraction thresholds, verification
rules, and application instructions do not define company help or DataPilot
behavior.

## Update rules

- Add approved company reference documents only; record their owner, review
  date, and intended scope when adding or replacing a source.
- Keep one canonical source for each policy and resolve conflicting policy text
  before indexing it.
- Keep DataPilot feature documentation, workbook instructions, analytics,
  dashboards, and agent execution policies outside this package.
- User uploads remain session evidence and never become company policy sources.
- The loader indexes PDF, DOCX, and UTF-8 TXT files. Markdown files describe the
  package and are not retrieved as answer evidence.
