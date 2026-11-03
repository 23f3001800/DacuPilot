<script setup>
import { onMounted, ref } from "vue";
import { getGeneratedCharts, getWorkbookSchema } from "../api";
import { getWorkbookThreadId, getWorkspaceStorageKey } from "../workbookSession.js";

const threadId = getWorkbookThreadId();
const loading = ref(true);
const error = ref("");
const schema = ref(null);
const charts = ref([]);
function readArray(key) { try { const value = JSON.parse(localStorage.getItem(key) || "[]"); return Array.isArray(value) ? value : []; } catch { return []; } }
const hiddenCharts = ref(readArray(getWorkspaceStorageKey("insightpilot-hidden-dashboard-charts", threadId)));
const visibleCharts = ref([]);
const chartFilter = ref("all");
const chartOrder = ref(readArray(getWorkspaceStorageKey("insightpilot-dashboard-order", threadId)));

function syncVisibility() {
  const ordered = [...charts.value].sort((left, right) => {
    const leftIndex = chartOrder.value.indexOf(left.url);
    const rightIndex = chartOrder.value.indexOf(right.url);
    return (leftIndex < 0 ? Number.MAX_SAFE_INTEGER : leftIndex) - (rightIndex < 0 ? Number.MAX_SAFE_INTEGER : rightIndex);
  });
  visibleCharts.value = ordered.filter((chart) => !hiddenCharts.value.includes(chart.url) && (chartFilter.value === "all" || chart.column === chartFilter.value));
}
function moveChart(chart, direction) {
  const order = [...charts.value].sort((left, right) => {
    const leftIndex = chartOrder.value.indexOf(left.url);
    const rightIndex = chartOrder.value.indexOf(right.url);
    return (leftIndex < 0 ? Number.MAX_SAFE_INTEGER : leftIndex) - (rightIndex < 0 ? Number.MAX_SAFE_INTEGER : rightIndex);
  });
  const index = order.findIndex((item) => item.url === chart.url);
  const target = index + direction;
  if (target < 0 || target >= order.length) return;
  [order[index], order[target]] = [order[target], order[index]];
  chartOrder.value = order.map((item) => item.url);
  localStorage.setItem(getWorkspaceStorageKey("insightpilot-dashboard-order", threadId), JSON.stringify(chartOrder.value));
  syncVisibility();
}
function toggleChart(chart) {
  hiddenCharts.value = hiddenCharts.value.includes(chart.url) ? hiddenCharts.value.filter((url) => url !== chart.url) : [...hiddenCharts.value, chart.url];
  localStorage.setItem(getWorkspaceStorageKey("insightpilot-hidden-dashboard-charts", threadId), JSON.stringify(hiddenCharts.value));
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
  } catch (caught) {
    error.value = caught.message;
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
    <div v-else-if="error" class="workflow-error" role="alert">{{ error }}</div>
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
      <section class="dashboard-controls panel"><strong>Dashboard charts</strong><label>Filter by field<select v-model="chartFilter" @change="syncVisibility"><option value="all">All fields</option><option v-for="column in [...new Set(charts.map(chart => chart.column).filter(Boolean))]" :key="column" :value="column">{{ column }}</option></select></label><label v-for="chart in charts" :key="chart.url"><input type="checkbox" :checked="!hiddenCharts.includes(chart.url)" @change="toggleChart(chart)" /> {{ chart.title }}</label></section>
      <section class="dashboard-canvas">
        <article v-for="(chart, index) in visibleCharts" :key="`${chart.url}-${index}`" class="panel dashboard-widget">
          <div class="chart-title"><div><h2>{{ chart.title }}</h2><small>{{ chart.category_column ? `${chart.column} grouped by ${chart.category_column}` : chart.column }} · generated from workbook</small></div><div class="widget-actions"><button :disabled="index === 0" @click="moveChart(chart, -1)" aria-label="Move chart earlier">↑</button><button :disabled="index === visibleCharts.length - 1" @click="moveChart(chart, 1)" aria-label="Move chart later">↓</button><span>Chart {{ index + 1 }}</span></div></div>
          <img class="saved-chart-image" :src="chart.url" :alt="chart.title" />
        </article>
      </section>
    </template>
  </section>
</template>
