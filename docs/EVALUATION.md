# Evaluation methods and traces

The measured snapshot is in `backend/evals/evaluation_results.json`. Each live
case contains its expected output, checks, returned answer, elapsed time, and
observable event trace. The snapshot identifies the code revision, runner hash,
Python version, model configuration, and start time. The final backend source
revision is `22c9a14`, and its worktree flag was false at measurement time.

## Dataset and grading

The workbook has five rows, four original columns, a revenue total of 500,
and one missing Cost cell. Expected references are specified independently in
the runner. Approved Profit values are 60, 30, 20, null, and 40.

Three source questions use the checked-in company handbook. Each has a target
number and an exact expected source section. Groundedness checks require both
to appear in the returned answer. Citation validity checks resolve labels to
the loaded corpus. These tests do not perform sentence-level semantic entailment.

Four assistance behavior cases cover general answers, workbook handoff,
injection rejection, and unsupported company policy. Their literal matchers are
limited. A previous unsupported-policy answer correctly declined the request,
but its wording failed the automatic matcher. The final run passed all seven
behavior checks. The earlier run is retained in the
[baseline snapshot](https://github.com/23f3001800/DacuPilot/blob/d5b3c9f/backend/evals/evaluation_results.json).

The document fixture is a generated two-page PDF with eight printed reference fields.
Classification is checked by page identity. Exact field match normalizes case
and whitespace. Character error rate uses character edit distance divided by
reference length, capped at one by the application's evaluator. Raw OCR is a
separate request on the first page. Both pipeline pages used direct multimodal
extraction and correctly skipped OCR. OCR provider confidence is excluded from
accuracy calculations.

## Observed traces

Times below are elapsed milliseconds within each request. The JSON contains
the complete event sequences. These are application execution events, with no
private model reasoning requested or recorded.

| Path | Observed sequence | Result |
| --- | --- | --- |
| Total Revenue | Thinking → calculation tool start → successful tool result → workbook citation → evaluation → completion | 500 in 5,317 ms |
| Approved column change | Change preview → inspect original schema → explicit apply request → read refreshed preview | Original sheet retained four columns until apply. Profit values matched all five rows. |
| Handbook answer | Search company sources → retrieved sections → streamed generation → validated final answer → evaluation → completion | Annual leave of 24 days with the expected page-5 citation |
| Document page 1 | Image extraction starts at 73 ms → assessed at 8,607 ms → OCR skipped → classification and validation complete | One multimodal attempt, no review items |
| Document page 2 | Image extraction starts at 8,609 ms → assessed at 15,007 ms → OCR skipped → classification and validation complete | One multimodal attempt, no review items |
| Document job | Segmentation → direct image processing → grouping → review → export → completion | Two documents, eight matched fields, four downloadable outputs in 15,027 ms |
| Separate raw OCR check | Azure DNS failure → Google billing rejection → vision OCR | Normalized character error rate of zero on the first printed page |

## Parameter decisions

Top-k sensitivity uses one ranked retrieval result per question and truncates it
at k = 1, 3, and 5. Hit rate measures whether the expected section is present.
MRR averages the reciprocal rank of the first expected section. Results are
perfect on these three straightforward questions, with no evidence to select a
different production k.

The field-threshold sweep reuses extracted field scores at 0.75, 0.85, and 0.95.
Acceptance requires a nonempty value, a passing format check, and a score at or
above the threshold. All eight clear printed fields pass each setting. A labeled
set containing wrong, uncertain, handwritten, and missing fields is needed to
compare false acceptance and false review rates.

Temperatures, chunk dimensions, worker limits, handwriting penalty, the one-retry
budget, and the production field threshold were configured manually. There was no temperature
grid search, model-weight fine-tuning, or held-out confidence calibration.

## Failures found during verification

| Finding | Cause | Handling |
| --- | --- | --- |
| Old benchmark presented synthetic outputs as measured performance | Simulated answers, a fixed 0.96 analyst score, and added OCR timing constants | Replaced with fixture-driven code checks and live HTTP measurements. |
| Local sandbox smoke cases timed out in the first evaluator run | Spawned workers reimported eager company-retrieval initialization | Moved retrieval imports inside evaluation functions. Kept the five-second worker deadline. Final direct calculation checks passed 4 / 4. |
| Correct numbers at sentence endings failed grading | The original numeric matcher rejected punctuation after a value | Corrected the matcher and added a regression test. |
| Unresolved evidence ranges appeared in an answer | The citation formatter supported individual markers but left ranges visible | Strip unresolved range markers. Existing source-label validation remains in place. |
| Azure OCR request failed | DNS could not resolve the configured endpoint | Vision fallback completed after the Google attempt also failed. |
| Google Document AI request failed | The configured project had billing disabled | The fallback event records PermissionDenied. No account or billing changes were made. |
| Unsupported-policy case failed an earlier automatic behavior check | Literal matcher omitted the phrase “could not find” | Preserved the failed score in the baseline snapshot. The final run's wording matched the grader. |
| Document fields were absent from the frontend review table | The table read flat fields while the API returned an extraction block | Read nested and legacy flat structures. Added three frontend regressions and exposed attempt summaries. |

## Multimodal-first retry policy

The image and document field definitions are sent to the configured multimodal
model in one classification-and-extraction request. The same schema and field
normalization functions assess primary and retry results.

- Skip OCR when classification and every required field pass the configured
  threshold, missing-value checks, format checks, and handwriting adjustment.
- Otherwise perform one logical OCR-assisted retry. OCR provider failover runs
  Azure → Google → vision. Recognized text then feeds classification and extraction.
- Prefer the attempt with fewer review items, using classification confidence
  to break a tie. An exact tie retains the primary image result.
- Flag conflicting nonempty values or different supported document types for
  human review. Preserve those flags when grouping continuation pages.
- Retain an uncertain primary result if OCR fails. If both paths fail, return an
  unknown document for review, with both failed attempt summaries.

Thirteen controlled regression cases cover the retry policy, real image payload
construction, failure behavior, and continuation-page flag preservation. The
live pages were clear enough to skip OCR. Low-confidence retry control was
verified with controlled responses, rather than a live handwriting benchmark.

## Reproduction boundaries

The run used the configured Azure OpenAI-compatible `gpt-5-mini` deployment as
the primary model. OCR fallback is labeled `vision_llm`; the current trace does
not identify which underlying model provider ultimately served a fallback call.
No provider-by-provider model ablation was performed.

Test-suite success verifies regressions and contracts, including mocked provider
paths. The live smoke results separately verify real external calls on these
specific fixtures. Neither establishes production accuracy on all ten supported
document schemas or establishes a general hallucination rate.
