# Evaluation methods and traces

The measured snapshot is in `backend/evals/evaluation_results.json`. Each live
case contains its expected output, checks, returned answer, elapsed time, and
observable event trace. The snapshot identifies the code revision, runner hash,
Python version, model configuration, and start time. The worktree flag was true
because the previous generated results file was already modified.

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
limited. The final unsupported-policy answer correctly declined the request,
but its wording failed the automatic matcher. That failed grade is retained.

The OCR fixture is a generated two-page PDF with eight printed reference fields.
Classification is checked by page identity. Exact field match normalizes case
and whitespace. Character error rate uses character edit distance divided by
reference length, capped at one by the application's evaluator. Raw OCR is a
separate request on the first page. OCR provider confidence is excluded from
accuracy calculations.

## Observed traces

Times below are elapsed milliseconds within each request. The JSON contains
the complete event sequences. These are application execution events, with no
private model reasoning requested or recorded.

| Path | Observed sequence | Result |
| --- | --- | --- |
| Total Revenue | Thinking → calculation tool start → successful tool result → workbook citation → evaluation → completion | 500 in 5,527 ms |
| Approved column change | Change preview → inspect original schema → explicit apply request → read refreshed preview | Original sheet retained four columns until apply. Profit values matched all five rows. |
| Handbook answer | Search company sources → retrieved sections → streamed generation → validated final answer → evaluation → completion | Annual leave of 24 days with the expected page-5 citation |
| OCR page 1 | Azure fallback at 165 ms → Google fallback at 716 ms → vision OCR → classification → extraction | Both provider failures were exposed as typed progress events. |
| OCR page 2 | Azure fallback at 14,837 ms → Google fallback at 14,995 ms → vision OCR → classification → extraction | The second page used the same fallback hierarchy. |
| OCR job | Segmentation → page processing → grouping → review → export → completion | Two documents, eight matched fields, four downloadable outputs |

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

Temperatures, chunk dimensions, worker limits, handwriting penalty, and the
production field threshold were configured manually. There was no temperature
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
| Unsupported-policy case failed the final automatic behavior check | Literal matcher omitted the phrase “could not find” | Retained the failed score and documented manual review of the actual answer. |

## Reproduction boundaries

The run used the configured Azure OpenAI-compatible `gpt-5-mini` deployment as
the primary model. OCR fallback is labeled `vision_llm`; the current trace does
not identify which underlying model provider ultimately served a fallback call.
No provider-by-provider model ablation was performed.

Test-suite success verifies regressions and contracts, including mocked provider
paths. The live smoke results separately verify real external calls on these
specific fixtures. Neither establishes production accuracy on all ten supported
document schemas or establishes a general hallucination rate.
