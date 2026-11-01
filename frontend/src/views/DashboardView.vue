<script setup>
import { onMounted, ref } from "vue";
import { getGeneratedCharts, getWorkbookSchema } from "../api";

const threadId = sessionStorage.getItem("datapilot-thread-id") || "default";
const loading = ref(true);
const schema = ref(null);
const charts = ref([]);
const hiddenCharts = ref(JSON.parse(localStorage.getItem("insightpilot-hidden-dashboard-charts") || "[]"));
const visibleCharts = ref([]);

function syncVisibility() { visibleCharts.value = charts.value.filter((chart) => !hiddenCharts.value.includes(chart.url)); }
function toggleChart(chart) {
  hiddenCharts.value = hiddenCharts.value.includes(chart.url) ? hiddenCharts.value.filter((url) => url !== chart.url) : [...hiddenCharts.value, chart.url];
  localStorage.setItem("insightpilot-hidden-dashboard-charts", JSON.stringify(hiddenCharts.value));
  syncVisibility();
}
function exportDashboard() {
  const content = JSON.stringify({ title: "InsightPilot workbook dashboard", dataset: schema.value?.filename, exportedAt: new Date().toISOString(), charts: visibleCharts.value }, null, 2);
  const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
  const link = document.createElement("a"); link.href = url; link.download = "insightpilot-dashboard.json"; link.click(); URL.revokeObjectURL(url);
}

onMounted(async () => {
  try {
    [schema.value, { charts: charts.value }] = await Promise.all([
      getWorkbookSchema(threadId),
      getGeneratedCharts(threadId),
    ]);
    syncVisibility();
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section class="product-page dashboard-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">Agent-generated workspace</p>
        <h1>Dashboards</h1>
        <p class="page-lead">Build a dashboard from charts generated against the active workbook.</p>
      </div>
      <div v-if="schema?.loaded" class="dashboard-actions"><span class="live-tag"><i /> {{ schema.filename }}</span><button class="secondary-button" @click="syncVisibility">↻ Refresh</button><button class="primary-button" @click="exportDashboard">Export dashboard</button></div>
    </div>

    <div v-if="loading" class="loading-card">Loading generated dashboard artifacts…</div>
    <div v-else-if="!schema?.loaded" class="empty-product">
      <span>▦</span><h2>No workbook connected</h2>
      <p>Upload a workbook in Data before creating an analysis dashboard.</p>
    </div>
    <div v-else-if="!charts.length" class="empty-product">
      <span>◒</span><h2>No dashboard artifacts yet</h2>
      <p>Ask InsightPilot Analyst for a chart or trend. Only chart artifacts generated from this workbook can be added here.</p>
    </div>
    <template v-else>
      <div class="analytics-kpis dashboard-kpis">
        <article class="metric-card"><span>Dashboard charts</span><strong>{{ charts.length }}</strong><small>Generated from the active workbook</small></article>
        <article class="metric-card"><span>Rows analysed</span><strong>{{ schema.total_rows.toLocaleString() }}</strong><small>{{ schema.filename }}</small></article>
        <article class="metric-card"><span>Available fields</span><strong>{{ schema.columns.length }}</strong><small>Use Data workspace to modify columns</small></article>
      </div>
      <section class="dashboard-controls panel"><strong>Dashboard charts</strong><label v-for="chart in charts" :key="chart.url"><input type="checkbox" :checked="!hiddenCharts.includes(chart.url)" @change="toggleChart(chart)" /> {{ chart.title }}</label></section>
      <section class="dashboard-canvas">
        <article v-for="(chart, index) in visibleCharts" :key="`${chart.url}-${index}`" class="panel dashboard-widget">
          <div class="chart-title"><div><h2>{{ chart.title }}</h2><small>{{ chart.column }} · verified workbook artifact</small></div><span>Chart {{ index + 1 }}</span></div>
          <img class="saved-chart-image" :src="chart.url" :alt="chart.title" />
        </article>
      </section>
    </template>
  </section>
</template>
