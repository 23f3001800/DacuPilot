<script setup>
import { computed, onMounted, ref } from "vue";
import { getGeneratedCharts, getWorkbookDashboard, getWorkbookSchema } from "../api";
import { getWorkbookThreadId } from "../workbookSession.js";

const emit = defineEmits(["navigate"]);
const threadId = getWorkbookThreadId();
const overviewQuestion = ref("");
const loading = ref(true);
const schema = ref(null);
const dashboard = ref(null);
const charts = ref([]);
const suggestedQueries = computed(() => {
  if (!schema.value?.loaded) return ["Summarize an uploaded workbook", "Find missing values", "Show a useful chart"];
  const numeric = schema.value.columns.find((column) => ["number", "currency", "numeric text"].includes(schema.value.semantic_types?.[column]) || /int|float|decimal|double|numeric/i.test(schema.value.data_types?.[column] || ""));
  const category = schema.value.columns.find((column) => column !== numeric && ["category", "date", "date text"].includes(schema.value.semantic_types?.[column]));
  return [
    `Summarize ${schema.value.filename}`,
    numeric && category ? `Show ${numeric} by ${category} as a chart` : "Show a useful chart from this workbook",
    "Which fields have missing values?",
    "Create a dashboard from this workbook",
  ];
});
function go(id, query = null) { emit("navigate", { id, query }); }
function submitOverviewQuestion() {
  const query = overviewQuestion.value.trim();
  go("data-agent", query || null);
  overviewQuestion.value = "";
}
function formatNumber(value) { return typeof value === "number" ? value.toLocaleString() : value; }

onMounted(async () => {
  try {
    [schema.value, dashboard.value] = await Promise.all([getWorkbookSchema(threadId), getWorkbookDashboard(threadId)]);
    charts.value = (await getGeneratedCharts(threadId)).charts || [];
  } catch { /* Empty state before the first upload. */ }
  finally { loading.value = false; }
});
</script>

<template>
  <section class="overview-page">
    <div class="overview-hero"><div><p class="eyebrow">Workspace overview</p><h1>Good morning, Vikas</h1><p>Turn your data into clear, verifiable business insight.</p></div><button class="primary-button" @click="go('data-agent')">＋ New analysis</button></div>
    <form class="overview-query" role="search" @submit.prevent="submitOverviewQuestion"><span aria-hidden="true">✦</span><input v-model="overviewQuestion" aria-label="Ask the Data Analysis Agent" placeholder="Ask anything about your data..." /><button type="submit" aria-label="Open Data Analysis Agent">→</button></form>
    <div class="suggested-queries"><button v-for="query in suggestedQueries" :key="query" @click="go('data-agent', query)">{{ query }}</button></div>
    <div class="overview-kpis"><article class="metric-card"><span>Connected workbooks</span><strong>{{ loading ? '—' : schema?.loaded ? 1 : 0 }}</strong><small>{{ schema?.loaded ? schema.filename : 'Upload a workbook to begin' }}</small></article><article class="metric-card"><span>Rows available</span><strong>{{ loading ? '—' : formatNumber(schema?.loaded ? schema.total_rows : 0) }}</strong><small>From the active workspace</small></article><article class="metric-card"><span>Generated charts</span><strong>{{ loading ? '—' : charts.length }}</strong><small>Created from real analysis</small></article><article class="metric-card"><span>Data quality signals</span><strong>{{ loading ? '—' : dashboard?.loaded ? formatNumber(dashboard.kpis?.find(k => k.label === 'Missing values')?.value || 0) : '—' }}</strong><small>Missing values detected</small></article></div>
    <div class="overview-grid"><section class="panel activity-panel"><div class="panel-heading"><div><h2>Agent activity</h2><p class="helper">Transparent execution from your active workspace</p></div><span class="live-tag"><i /> Live</span></div><div class="activity-empty" v-if="!schema?.loaded"><span>✦</span><b>Ready for your first analysis</b><p>Upload an Excel workbook in Data, then ask InsightPilot Analyst a question.</p><button class="secondary-button" @click="go('data-agent')">Open Data workspace →</button></div><div v-else class="activity-list"><div><i class="done">✓</i><span>Workbook loaded<small>{{ schema.filename }}</small></span></div><div><i class="done">✓</i><span>Schema available<small>{{ schema.columns.length }} fields · {{ schema.total_rows.toLocaleString() }} rows</small></span></div><div><i :class="charts.length ? 'done' : 'active'">{{ charts.length ? '✓' : '·' }}</i><span>{{ charts.length ? 'Visualization generated' : 'Waiting for an analysis' }}<small>{{ charts.length ? `${charts.length} saved chart artifact(s)` : 'Ask for a chart to continue' }}</small></span></div></div></section><section class="panel dashboard-panel"><div class="panel-heading"><div><h2>Recent dashboards</h2><p class="helper">Only agent-generated artifacts appear here</p></div><button class="text-button" @click="go('dashboards')">View all →</button></div><div v-if="charts.length" class="dashboard-preview"><div v-for="chart in charts.slice(-2)" :key="chart.url" class="dashboard-thumb"><img :src="chart.url" :alt="chart.title" /><b>{{ chart.title }}</b><small>Generated from workbook</small></div></div><div v-else class="empty-dashboard"><span>▦</span><p>No dashboards yet</p><small>Charts generated in Data Analysis will appear here.</small></div></section></div>
    <div class="overview-modules"><button type="button" class="module-card" @click="go('data-agent')"><span class="module-icon blue">▤</span><div><b>Data Analysis</b><p>Explore, modify, and visualize uploaded workbooks with the agent.</p></div><span aria-hidden="true">→</span></button><button type="button" class="module-card" @click="go('documents')"><span class="module-icon purple">▣</span><div><b>DocuLens</b><p>Ask general questions and extract traceable information from documents.</p></div><span aria-hidden="true">→</span></button><button type="button" class="module-card" @click="go('workflows')"><span class="module-icon green">✣</span><div><b>Agent workflows</b><p>Run a transparent profiling and analysis workflow on the active workbook.</p></div><span aria-hidden="true">→</span></button></div>
  </section>
</template>
