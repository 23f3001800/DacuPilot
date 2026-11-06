# Evaluation methods

The README contains the three result tables. Machine-readable cases, responses,
source quotations, and scores are retained in
`backend/evals/parameter_study_results.json`. Earlier application smoke checks
are in `backend/evals/evaluation_results.json`.

## Data and split

The retrieval study uses the checked-in Nimbus Orchard handbook. Eight
development questions cover single-section questions, two multi-section
questions, and one unsupported topic. Six held-out questions ask about different
facts on the same source pages. This is a question-level split within one
handbook. It does not estimate transfer to unseen companies or document sets.

Relevant source sections and expected answer facts are specified in the runner
before scoring. The held-out references cover eight-day annual-leave carryover,
20-week primary-caregiver leave, USD 49 Sprout pricing, the 30-percent non-profit
discount, access removal within two hours, and a two-section question about
six-week secondary-caregiver leave plus USD 9 additional Grove users.

Baseline and selected configurations each generate two responses to every
held-out question. These 24 responses receive separate model-judge calls.
The production company-answer node and citation validator generate the answers
using frozen retrieval results. This study controls retrieval inputs within the
answer node. The separate smoke suite exercises the HTTP APIs.

## Groundedness definitions

- **Citation coverage** is attributed factual sentences divided by all judged
  factual sentences. An attribution must resolve to a source label present in both
  the returned answer and the retrieved evidence.
- **Faithfulness** is evidence-supported factual sentences divided by all judged
  factual sentences. A supported sentence can be uncited. A separate support-source ID
  allows this score to remain independent of citation coverage.
- **Citation precision** is supported attributed sentences with a matching
  supporting-source citation divided by attributed sentences. This is a
  sentence-level attribution metric. A correct source label alone does not
  establish support.
- **Reference-fact recall** is correctly conveyed target facts divided by the
  expected facts. It measures answer completeness against the small labeled set.
- **Valid answer grades** reports usable grades against attempted answers.
  Parse failures, missing sentence judgments, invalid IDs, and malformed fact
  lists are retained as grading errors and excluded from sentence denominators.

Code splits the answer into fixed sentence units and assigns stable IDs. A
citation-only segment is attached to the immediately preceding sentence. The
judge labels which units assert facts and whether their complete factual content
is entailed by retrieved text. Source IDs identify individual chunks, including
multiple chunks with the same public citation label. Supporting quotations must
occur literally in that chunk after case and whitespace normalization.
Fabricated quotations cannot count as support. Four regression tests cover
retrieval denominators, faithful-but-uncited content, fabricated quotations,
and correct handling of repeated citation labels.

The judge uses the same configured provider family as answer generation.
Factual-sentence selection and entailment remain model-assisted judgments.
Compound sentences are coarser units than atomic claims. The checks do not
constitute independent human labeling or confidence calibration. Answers with no
factual units still contribute to reference-fact recall. The raw sentence records
allow individual scores to be reviewed.

These are conservative, quote-verified support proxies. A factual label on a
statement about missing evidence can reduce the support score because an absence
has no positive source quotation. Such cases can be inspected in the retained
sentence records. The score is not a measured hallucination rate.

The initial free-text grader produced malformed source labels and copied claim
spans that did not match answers. Its scores were rejected. The same generated
answers were regraded with stable sentence and source IDs. Initial grading
records remain under `initial_grader_result` for audit. No answer was regenerated
for this correction, and held-out labels did not select configurations.

## Retrieval precision, recall, and F1

The evaluation unit is a unique source section among the top-k returned chunks.
Duplicate chunks from one section count once. A relevant returned section is a
true positive, an irrelevant returned section is a false positive, and a missed
relevant section is a false negative. Unsupported-topic cases contribute false
positives when retrieval returns evidence.

Micro precision is TP / (TP + FP), micro recall is TP / (TP + FN), and F1 is the
harmonic mean of those values. Counts are summed across questions before ratios
are calculated. MRR is also recorded in the JSON. The report lists TP, FP, FN,
returned source sections, and labeled sections for each configuration.

## One-factor experiments and selection

The baseline is k=5, chunk size 1,200 characters, overlap 180 characters, and
minimum score 0.15. The eight alternatives vary one factor at a time.

- Top-k changes to 1 or 3.
- Chunk size changes to 800 or 1,600 characters with overlap fixed at 180.
- Overlap changes to 90 or 270 characters with chunk size fixed at 1,200.
- Minimum score changes to 0.35 or 0.55.

Individual development-F1 winners are also combined in a tenth trial. The best
of these measured configurations is selected using development micro-F1 alone.
Exact ties keep the earlier baseline settings. Held-out answers and labels do
not select hyperparameters. Each chunk geometry has an isolated in-memory
Chroma collection so indexes cannot reuse stale text across chunk settings.
Retrieval scores and source text are recorded before answer generation.

Top-k also controls the retriever's existing three-times-k vector candidate
request. The embedding function and source corpus are fixed. Production settings
are preserved because the best-F1 candidate loses held-out source recall.
This experiment searches a bounded neighborhood and does not establish a global
or production-wide optimum.

The held-out answer traces exposed a separate company-source routing weakness.
Some Sprout pricing and non-profit discount questions used the general-answer
path even when the retrieved handbook contained the reference facts. Those
responses were retained. This explains why high retrieval recall does not ensure
high answer reference-fact recall. No routing fix was applied during this
evaluation-focused change.

Analyst temperature 0.1, assistance temperature 0.0, field review threshold 0.85,
handwriting penalty 0.20, worker limits, and the one-OCR-retry policy remain
fixed. They are documented engineering choices. No temperature sweep,
model-weight fine-tuning, or held-out confidence calibration was performed.

## Other module scores

The application smoke suite uses a generated five-row workbook with total
Revenue 500 and one missing Cost. It checks three numeric answers, consent,
approved Profit values, and a downloadable chart. Number-presence checks plus
tool success and citations do not exhaustively verify every generated sentence.

Document extraction uses a generated two-page PDF containing eight required
printed fields. A nonempty field equal to its reference after case and whitespace
normalization is a true positive. An incorrect nonempty value is a false positive
and a missed reference, while an empty required field is a missed reference.
The current sample has eight correct fields with no false positives or misses.
Character error rate is character edit distance divided by reference length,
averaged over fields and capped at one by the application evaluator.

Both live pages passed direct multimodal extraction and skipped OCR. The separate
raw-OCR check reached vision OCR after Azure DNS resolution and Google billing
failures. Retry control uses 13 controlled regressions covering low scores,
missing fields, invalid formats, handwriting adjustment, provider failures,
disagreements, and continuation-page review flags. Live handwriting quality
remains unmeasured.

## Reproduce

From `backend` with the repository virtual environment activated, run
`python -m evals.parameter_study` for local retrieval experiments. Add
`--live --repetitions 2` for the 24 answer-generation and 24 judging requests.
The live flag uses configured external services and writes the report after
each completed answer configuration. Fresh session IDs isolate answer state.

Run `python -m evals.run_all_evaluations --live` against the backend on port 8000
to reproduce the separate module smoke results. `pytest -q` and the frontend's
`npm test` cover code regressions separately from model-quality scores.

`python -m evals.parameter_study --regrade` applies the current grader to saved
answers without generating new answers. The report records the grading revision.
