<script setup>
import { onMounted, ref } from "vue";
import { getWorkbookSchema } from "../api";
import { preferences } from "../preferences.js";
import { getWorkbookThreadId, getWorkspaceStorageKey } from "../workbookSession.js";

const threadId = getWorkbookThreadId();
const schema = ref(null);
const analyses = ref([]);
const loading = ref(true);
const error = ref("");

function loadAnalyses() {
  try { analyses.value = JSON.parse(localStorage.getItem(getWorkspaceStorageKey("insightpilot-analyses", threadId)) || "[]"); }
  catch { analyses.value = []; }
}

function confidence(value) {
  if (value === null || value === undefined || value === "") return "Not scored";
  const score = Number(value);
  return Number.isFinite(score) ? `${Math.round(score <= 1 ? score * 100 : score)}%` : "Not provided";
}

onMounted(async () => {
  loadAnalyses();
  try { schema.value = await getWorkbookSchema(threadId); }
  catch (caught) { error.value = caught.message; }
  finally { loading.value = false; }
});
</script>

<template>
  <section class="product-page analytics-page">
    <div class="page-heading"><div><p class="eyebrow">InsightPilot Analyst</p><h1>Analysis Workspace</h1><p class="page-lead">Review actual questions, agent responses, available evidence, and generated workbook charts.</p></div><span v-if="schema?.loaded" class="live-tag"><i /> {{ schema.filename }}</span></div>
    <div v-if="loading" class="loading-card">Loading workbook analysis…</div>
    <div v-else-if="error || !schema?.loaded" class="empty-product"><span>◒</span><h2>No active workbook</h2><p>{{ error || "Upload a workbook in Data to run and review analysis." }}</p></div>
    <template v-else>
      <div class="analytics-kpis"><article class="metric-card"><span>Analyst runs</span><strong>{{ analyses.length }}</strong><small>Saved from this workspace</small></article><article class="metric-card"><span>Workbook rows</span><strong>{{ schema.total_rows.toLocaleString() }}</strong><small>{{ schema.filename }}</small></article><article class="metric-card"><span>Fields</span><strong>{{ schema.columns.length }}</strong><small>Current workbook schema</small></article><article class="metric-card"><span>Evidence items</span><strong>{{ analyses.reduce((total, item) => total + (item.citations?.length || 0), 0) }}</strong><small>Returned with saved answers</small></article></div>
      <section v-if="analyses.length" class="panel analyst-results"><div class="panel-heading"><div><h2>Analysis results</h2><p class="helper">Completed requests from the Data workspace</p></div><button class="text-button" @click="loadAnalyses">↻ Refresh</button></div><article v-for="analysis in analyses" :key="analysis.id" class="analysis-result"><div class="analysis-result-top"><b>{{ analysis.question }}</b><time>{{ new Date(analysis.createdAt).toLocaleString() }}</time></div><p>{{ analysis.answer || "The agent returned no answer text." }}</p><div class="answer-meta"><span class="latency">Latency {{ analysis.latencyMs ?? "n/a" }} ms</span><span>Confidence {{ confidence(analysis.confidence) }}</span><template v-if="preferences.citations"><span>{{ analysis.citations?.length || 0 }} evidence item(s)</span></template></div><ul v-if="preferences.citations && analysis.citations?.length" class="analysis-citations"><li v-for="(citation, index) in analysis.citations" :key="index"><b>{{ citation.source || citation.title || citation }}</b><small v-if="citation.detail">{{ citation.detail }}</small></li></ul><figure v-if="analysis.chart" class="analysis-chart-output"><figcaption>{{ analysis.chart.title }} · generated from uploaded workbook</figcaption><img :src="analysis.chart.url" :alt="analysis.chart.title" /></figure></article></section>
      <div v-else class="empty-product"><span>◒</span><h2>No saved analyses yet</h2><p>Ask InsightPilot Analyst a question in Data. Completed answers will appear here with any returned citations and confidence.</p></div>
      <section class="panel data-profile"><div class="panel-heading"><div><h2>Active workbook schema</h2><p class="helper">{{ schema.filename }} · {{ schema.total_rows.toLocaleString() }} rows</p></div><span class="preview-count">{{ schema.columns.length }} fields</span></div><div class="profile-chips"><span v-for="column in schema.columns" :key="column">{{ column }} <small>{{ schema.data_types?.[column] || "unknown" }}</small></span></div></section>
    </template>
  </section>
</template>
