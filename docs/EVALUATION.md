# Evaluation methods

The README contains three summary tables. Machine-readable reports retain the
individual checks, answers, tool calls, outputs, timings, and pipeline trace events.
These experiments measure small synthetic workloads on the configured services.

## Cohorts and selection

**A-dev** is one five-row workbook. Columns are Region, Revenue, Cost, and Units.
Regions are North, South, North, West, East. Revenue values are 150, 80, 50, 120,
100. One Cost value is missing. Reference Revenue total is 500, mean is 100, and
regional totals are North 200, South 80, West 120, East 100.

Three analyst tasks request the Revenue total, mean, and regional totals. Each
is issued twice in a fresh conversation at each temperature, giving six requests
per setting. Temperatures run sequentially as 0.1, 0.0, 0.2. Other application
settings and provider configuration remain fixed. Highest development task-success
count wins. Exact ties retain the baseline, 0.1.

**A-test** is a value-held-out workbook with the same schema and regions. Revenue
values are 210, 140, 90, 60, 100. References are total 600, mean 120, and regional
totals North 300, South 140, West 60, East 100. It is scored only after selection.
It tests new values with the same question templates. It does not measure
generalization to unseen task families, schemas, or real-world datasets.

When the selected setting equals baseline, both names refer to the same six
held-out requests. They are not counted as twelve independent requests. The
repetitions measure run-to-run behavior on a shared workbook.

**A-flow** uses the A-dev workbook through the running HTTP/SSE application. Its
six checks cover consent rejection, three calculations, approved column persistence,
and a workbook-derived chart. The column test confirms Profit is absent before
approval and equals 60, 30, 20, null, 40 afterward. The chart check downloads SVG
from the server. The temporary workbook session is deleted afterward.

**X-test** is a generated two-page printed PDF with fixed annotations. One page
is a synthetic PAN card containing four fields. The other is a benefit illustration
with four fields. All identifiers and names are fabricated. Every schema field on
these two pages has a reference value. No threshold or model choice is selected
using this cohort. Its fixtures are available in `ocr_fixture()`.

## Analyst scoring

Execution accuracy is the number of requests with a correct calculation tool
result divided by requests. Scalars must parse as numbers and match their reference
within numerical tolerance. Regional results must contain the complete expected
label-to-value mapping. Failed, partial, malformed, or missing tool outputs fail.
The evaluator retains the actual generated tool arguments and outputs.

This adapts the principle of comparing executed results with gold results used
by Spider. The workload here uses restricted Pandas and synthetic Excel, with
its own oracles. [Spider evaluator](https://github.com/taoyds/spider/blob/master/evaluation.py)

Requested-fact correctness checks the final answer for the exact scalar, or each
region associated with its expected total. Numeric matching rejects a larger
number that merely contains the reference digits. Task success requires both
correct execution and correct requested facts, with no tool failure.

The answer checker is deliberately narrow. Additional prose can contain claims
outside its scoring scope. Full-response faithfulness would require separately
annotated claims and supporting execution evidence. It is currently unmeasured.

Workbook citation coverage is reported separately on A-flow calculation answers.
It requires a workbook citation event in each response. This checks source-event
availability. It does not establish claim-level entailment or citation precision.

Report latency as median and range over the six requests. No significance test
or population confidence interval is supported by this sample size. Runtime
heuristic confidence is not used as a correctness label.

## Extraction scoring

Classification accuracy divides correct document types by the two reference pages.
The two observed types cannot establish accuracy over all supported types.

Named field values are normalized by case folding and collapsing whitespace.
Correct nonempty values count as TP. Wrong nonempty values count as FP and FN.
Missing expected values count as FN. Unexpected nonempty predictions count as FP.
Micro precision is TP/(TP+FP), recall is TP/(TP+FN), and F1 is their harmonic mean.
Zero denominators return zero in the field helper. The fixture has eight populated
reference fields. [Document AI evaluation](https://docs.cloud.google.com/document-ai/docs/evaluate)

Whole-document exact match requires correct classification and every expected
field. The field corpus CER sums character edit distances across normalized
fields and divides by the total reference characters. Empty-reference corpus
CER is undefined and stored as null. A separate raw OCR check compares normalized
full-page text with all printed lines on the first page.

CER permits values greater than 1 when insertions exceed the reference length.
The runtime text-quality gate clamps its derived 1-CER confidence at zero, while
preserving the actual CER. [CER implementation and definition](https://github.com/huggingface/evaluate/blob/main/metrics/cer/cer.py)

The local CER helper uses 0 for two empty strings and 1 for an empty reference
with nonempty output. The populated-reference corpus is used for reported scores.
Export checks require successful HTTP responses and record payload sizes. They
check availability and can be supplemented with downstream schema checks.

## Parameters and observed behavior

All three analyst temperatures scored six successful A-dev requests. The tie rule
retained 0.1, which scored six successful A-test requests. Their latency differences
are descriptive because request order and service load were not randomized.

Threshold replay applies 0.75, 0.85, and 0.95 to the same saved field scores,
requiring nonempty values and passing format checks. All eight fields pass every
threshold. This provides no basis for an optimal threshold. Production retains
0.85, a handwriting penalty of 0.20, provider-default image sampling, and one logical
OCR-assisted retry. The handwriting penalty has no measured sensitivity study.

Primary image extraction completed both X-test pages without an OCR retry. In the
separate OCR check, Azure failed DNS resolution, Google Document AI returned
billing-disabled, and vision OCR recovered the reference text. Fallback failures
are operational findings and should not be interpreted as provider accuracy scores.

Controlled regression tests exercise low confidence, missing fields, conflicts,
provider errors, and retry limits. Those deterministic tests validate behavior.
They are separate from live labeled quality measurements. Larger held-out samples,
noisy scans, handwriting, optional/absent fields, and all remaining document types
need dedicated annotations. No model-weight fine-tuning or score calibration was run.

## Reproduction and traces

From the repository root, activate `.venv` and install `backend/requirements-dev.txt`.
Run from `backend`.

```bash
../.venv/bin/pytest -q
../.venv/bin/python -m evals.run_all_evaluations
../.venv/bin/python -m evals.run_all_evaluations --live
../.venv/bin/python -m evals.analyst_experiments --live --repetitions 2
```

Live pipeline checks require the backend at port 8000. The analyst experiment
invokes the normal graph in its own process, creates temporary workbooks, and
keeps dataset registrations in memory. It restores its model factory and clears
conversation checkpoints after each case. It does not write the shared workbook
registry. Each case has a 240-second bound, and partial experiment results are
saved after each development setting.

[Application results](../backend/evals/evaluation_results.json) retain SSE stages,
answers, checks, export responses, and document payloads.
[Analyst results](../backend/evals/analyst_experiment_results.json) retain the
cohort, temperature, repetition, oracle, answer, generated tool calls, actual
outputs, and latency. Both reports record source revision and runner checksum.

Reports may record an uncommitted source state because evaluation precedes the
final documentation commit. Scores can change on later live runs as models and
services change. Raw results are the source for the README summaries.
