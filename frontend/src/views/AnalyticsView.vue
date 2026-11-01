<script setup>
import { onMounted, ref } from "vue";
import { getGeneratedCharts, getWorkbookSchema } from "../api";

const threadId = sessionStorage.getItem("datapilot-thread-id") || "default";
const dashboard = ref(null);
const schema = ref(null);
const loading = ref(true);
const error = ref("");
const generatedCharts = ref([]);

function chartPoints(chart) {
  const values = chart?.series?.[0]?.values || [];
  if (!values.length) return "";
  const max = Math.max(...values.map(Number));
  const min = Math.min(...values.map(Number));
  const range = max - min || 1;
  return values.map((value, index) => `${(index / Math.max(1, values.length - 1)) * 100},${96 - ((Number(value) - min) / range) * 82}`).join(" ");
}

onMounted(async () => {
  try { schema.value = await getWorkbookSchema(threadId); generatedCharts.value = (await getGeneratedCharts(threadId)).charts || []; }
  catch (caught) { error.value = caught.message; }
  finally { loading.value = false; }
});
</script>

<template>
  <section class="product-page analytics-page"><div class="page-heading"><div><p class="eyebrow">Live workbook intelligence</p><h1>Analytics</h1><p class="page-lead">Turn the active workbook into a visual analysis dashboard with traceable metrics.</p></div><span class="live-tag"><i /> Live dataset</span></div>
    <div v-if="loading" class="loading-card">Loading the active workbook dashboard…</div>
    <div v-else-if="error" class="empty-product"><span>!</span><h2>No workbook connected</h2><p>{{ error }}</p><button class="primary-button">Open Data Studio →</button></div>
    <template v-else-if="schema?.loaded"><div class="analytics-kpis"><article class="metric-card"><span>Generated charts</span><strong>{{ generatedCharts.length }}</strong><small>Created from chat requests</small></article><article class="metric-card"><span>Workbook rows</span><strong>{{ schema.total_rows }}</strong><small>{{ schema.filename }}</small></article><article class="metric-card"><span>Workbook fields</span><strong>{{ schema.columns.length }}</strong><small>Active session</small></article></div><div v-if="generatedCharts.length" class="analytics-grid"><article v-for="(chart, index) in generatedCharts" :key="`${chart.title}-${index}`" class="panel analytics-chart"><div class="chart-title"><div><h2>{{ chart.title }}</h2><small>{{ chart.column }} · generated artifact</small></div><span>Chat output</span></div><img class="saved-chart-image" :src="chart.url" :alt="chart.title" /><div class="chart-axis"><span>{{ chart.labels[0] }}</span><span>{{ chart.labels[Math.floor(chart.labels.length / 2)] }}</span><span>{{ chart.labels.at(-1) }}</span></div></article></div><div v-else class="loading-card">No chart has been generated in chat yet. Ask the Document Assistant for a trend or graph.</div><section class="panel data-profile"><div class="panel-heading"><div><h2>Data profile</h2><p class="helper">{{ schema.filename }} · {{ schema.total_rows }} rows available</p></div><span class="preview-count">{{ schema.columns.length }} fields</span></div><div class="profile-chips"><span v-for="column in schema.columns" :key="column">{{ column }} <small>{{ schema.data_types[column] }}</small></span></div></section></template>
    <div v-else class="empty-product"><span>◒</span><h2>Connect a workbook to begin</h2><p>Upload an Excel workbook in Data Studio and this dashboard will populate with live KPIs and trends.</p></div>
  </section>
</template>
