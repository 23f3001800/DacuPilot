<script setup>
import { ref } from "vue";
import { getWorkbookThreadId, getWorkspaceStorageKey } from "../workbookSession.js";

const reports = ref([]);
const threadId = getWorkbookThreadId();
try {
  const jobs = JSON.parse(localStorage.getItem("insightpilot-document-jobs") || "[]");
  const workflows = JSON.parse(localStorage.getItem(getWorkspaceStorageKey("insightpilot-workflow-runs", threadId)) || "[]");
  const charts = JSON.parse(localStorage.getItem(getWorkspaceStorageKey("datapilot-generated-charts", threadId)) || "[]");
  const analyses = JSON.parse(localStorage.getItem(getWorkspaceStorageKey("insightpilot-analyses", threadId)) || "[]");
  reports.value = [
    ...jobs.map((job) => ({ id: job.job_id, title: `Document extraction · ${job.document_count} file(s)`, type: "Document extraction", date: job.createdAt, detail: `${job.page_count} pages · ${job.review_report?.flagged_fields?.length ?? 0} review flags`, url: job.outputs?.documents_json })),
    ...workflows.map((run) => ({ id: run.id, title: `Workbook analysis · ${run.filename || "active workbook"}`, type: "Analysis", date: run.createdAt, detail: `${run.rows} rows · ${run.fields} fields` })),
    ...charts.map((chart, index) => ({ id: `chart-${index}-${chart.title}`, title: chart.title, type: "Visualization", date: chart.generatedAt, detail: `${chart.column || "Workbook data"} · generated chart`, url: chart.url })),
    ...analyses.map((analysis) => ({ id: analysis.id, title: analysis.question, type: "Workbook analysis", date: analysis.createdAt, detail: `${analysis.filename || "Active workbook"} · ${analysis.latencyMs || "n/a"} ms`, answer: analysis.answer })),
  ].sort((a, b) => new Date(b.date || 0) - new Date(a.date || 0));
} catch { reports.value = []; }
</script>

<template>
  <section class="product-page reports-page">
    <div class="page-heading"><div><p class="eyebrow">Saved workspace outputs</p><h1>Reports</h1><p class="page-lead">A library of analysis and document outputs created in this browser.</p></div></div>
    <section v-if="reports.length" class="panel report-library">
      <div class="report-table-head"><span>Report</span><span>Type</span><span>Created</span><span>Output</span></div>
      <article v-for="report in reports" :key="report.id" class="report-row"><div><b>{{ report.title }}</b><small>{{ report.detail }}</small><small v-if="report.answer" class="report-answer">{{ report.answer }}</small></div><span>{{ report.type }}</span><time>{{ report.date ? new Date(report.date).toLocaleString() : "Date unavailable" }}</time><a v-if="report.url" :href="report.url" target="_blank" rel="noreferrer">Open output ↗</a><span v-else class="helper">Saved run</span></article>
    </section>
    <div v-else class="empty-product"><span>▤</span><h2>No reports saved yet</h2><p>Completed workbook workflows, generated charts, and document extraction jobs will appear here.</p></div>
  </section>
</template>
