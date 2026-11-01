<script setup>
import { onMounted, ref } from "vue";
import { getGeneratedCharts, getWorkbookDashboard, getWorkbookSchema } from "../api";

const emit = defineEmits(["navigate"]);
const threadId = sessionStorage.getItem("datapilot-thread-id") || "default";
const loading = ref(true);
const schema = ref(null);
const dashboard = ref(null);
const charts = ref([]);
function go(id) { emit("navigate", id); }
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
    <div class="overview-query" @click="go('data-agent')"><span>✦</span><span>Ask anything about your data...</span><b>→</b></div>
    <div class="suggested-queries"><button @click="go('data-agent')">Why did revenue change?</button><button @click="go('data-agent')">Show my top products</button><button @click="go('data-agent')">Find unusual patterns</button><button @click="go('data-agent')">Create a sales dashboard</button></div>
    <div class="overview-kpis"><article class="metric-card"><span>Connected workbooks</span><strong>{{ loading ? '—' : schema?.loaded ? 1 : 0 }}</strong><small>{{ schema?.loaded ? schema.filename : 'Upload a workbook to begin' }}</small></article><article class="metric-card"><span>Rows available</span><strong>{{ loading ? '—' : formatNumber(schema?.loaded ? schema.total_rows : 0) }}</strong><small>From the active workspace</small></article><article class="metric-card"><span>Generated charts</span><strong>{{ loading ? '—' : charts.length }}</strong><small>Created from real analysis</small></article><article class="metric-card"><span>Data quality signals</span><strong>{{ loading ? '—' : dashboard?.loaded ? formatNumber(dashboard.kpis?.find(k => k.label === 'Missing values')?.value || 0) : '—' }}</strong><small>Missing values detected</small></article></div>
    <div class="overview-grid"><section class="panel activity-panel"><div class="panel-heading"><div><h2>Agent activity</h2><p class="helper">Transparent execution from your active workspace</p></div><span class="live-tag"><i /> Live</span></div><div class="activity-empty" v-if="!schema?.loaded"><span>✦</span><b>Ready for your first analysis</b><p>Upload a CSV or Excel workbook in Data, then ask InsightPilot Analyst a question.</p><button class="secondary-button" @click="go('data-agent')">Open Data workspace →</button></div><div v-else class="activity-list"><div><i class="done">✓</i><span>Workbook loaded<small>{{ schema.filename }}</small></span></div><div><i class="done">✓</i><span>Schema available<small>{{ schema.columns.length }} fields · {{ schema.total_rows.toLocaleString() }} rows</small></span></div><div><i :class="charts.length ? 'done' : 'active'">{{ charts.length ? '✓' : '·' }}</i><span>{{ charts.length ? 'Visualization generated' : 'Waiting for an analysis' }}<small>{{ charts.length ? `${charts.length} saved chart artifact(s)` : 'Ask for a chart to continue' }}</small></span></div></div></section><section class="panel dashboard-panel"><div class="panel-heading"><div><h2>Recent dashboards</h2><p class="helper">Only agent-generated artifacts appear here</p></div><button class="text-button" @click="go('analytics')">View all →</button></div><div v-if="charts.length" class="dashboard-preview"><div v-for="chart in charts.slice(-2)" :key="chart.url" class="dashboard-thumb"><img :src="chart.url" :alt="chart.title" /><b>{{ chart.title }}</b><small>Generated from workbook</small></div></div><div v-else class="empty-dashboard"><span>▦</span><p>No dashboards yet</p><small>Charts generated in Data Analysis will appear here.</small></div></section></div>
    <div class="overview-modules"><article class="module-card" @click="go('data-agent')"><span class="module-icon blue">▤</span><div><b>Data Analysis</b><p>Explore, modify, and visualize uploaded workbooks with the agent.</p></div><span>→</span></article><article class="module-card" @click="go('documents')"><span class="module-icon purple">▣</span><div><b>DocuLens</b><p>Ask general questions and extract traceable information from documents.</p></div><span>→</span></article><article class="module-card" @click="go('workflows')"><span class="module-icon green">✣</span><div><b>Agent workflows</b><p>Run a transparent profiling and analysis workflow on the active workbook.</p></div><span>→</span></article></div>
  </section>
</template>
