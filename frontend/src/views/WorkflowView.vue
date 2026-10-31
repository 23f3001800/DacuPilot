<script setup>
import { computed, ref } from "vue";
import { getWorkbookDashboard, getWorkbookSchema } from "../api";

const running = ref(false);
const completed = ref(false);
const output = ref(null);
const error = ref("");
const stages = ref([
  { name: "Receive workbook", detail: "Use the active Excel session", state: "ready" },
  { name: "Profile columns", detail: "Read types, missing values, and sheets", state: "ready" },
  { name: "Generate analysis", detail: "Build KPIs and trends from real rows", state: "ready" },
  { name: "Prepare response", detail: "Return an evidence-backed result", state: "ready" },
]);
const status = computed(() => running.value ? "Agent is running" : completed.value ? "Workflow completed" : "Ready to run");
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function runWorkflow() {
  if (running.value) return;
  running.value = true; completed.value = false; output.value = null; error.value = "";
  stages.value.forEach((stage, index) => { stage.state = index === 0 ? "active" : "ready"; });
  try {
    const threadId = sessionStorage.getItem("datapilot-thread-id") || "default";
    const schema = await getWorkbookSchema(threadId);
    if (!schema.loaded) throw new Error("Upload a workbook in Data Studio before running this workflow.");
    stages.value[0].state = "done"; stages.value[1].state = "active"; await wait(350);
    stages.value[1].state = "done"; stages.value[2].state = "active";
    const dashboard = await getWorkbookDashboard(threadId);
    await wait(350); stages.value[2].state = "done"; stages.value[3].state = "active"; await wait(350);
    output.value = { filename: schema.filename, rows: schema.total_rows, fields: schema.columns.length, charts: dashboard.charts.length, missing: dashboard.kpis.find((item) => item.label === "Missing values")?.value ?? 0 };
    stages.value[3].state = "done"; completed.value = true;
  } catch (caught) { error.value = caught.message; const activeStage = stages.value.find((stage) => stage.state === "active"); if (activeStage) activeStage.state = "error"; }
  finally { running.value = false; }
}
</script>

<template><section class="product-page workflow-page"><div class="page-heading"><div><p class="eyebrow">Observable automation</p><h1>Agent Workflows</h1><p class="page-lead">Run a real workbook analysis and see the output produced by each stage.</p></div><span :class="['run-status', { running, completed }]"><i /> {{ status }}</span></div><div class="workflow-layout"><section class="panel workflow-card"><div class="workflow-card-head"><div><h2>Workbook analysis workflow</h2><p class="helper">Active session → profile → dashboard → result</p></div><button class="primary-button" :disabled="running" @click="runWorkflow">{{ running ? 'Running…' : completed ? 'Run again' : 'Run workflow' }} →</button></div><div class="workflow-steps"><div v-for="(stage, index) in stages" :key="stage.name" :class="['workflow-step', stage.state]"><span class="step-number">{{ stage.state === 'done' ? '✓' : stage.state === 'error' ? '!' : index + 1 }}</span><div><b>{{ stage.name }}</b><small>{{ stage.detail }}</small></div><span class="step-state">{{ stage.state === 'active' ? 'Working' : stage.state === 'done' ? 'Complete' : stage.state === 'error' ? 'Failed' : 'Waiting' }}</span></div></div><div v-if="error" class="workflow-error">{{ error }}</div></section><aside class="panel workflow-side"><span class="side-icon">✣</span><h2>Workflow output</h2><div v-if="output" class="workflow-output"><b>{{ output.filename }}</b><div><span>Rows<strong>{{ output.rows }}</strong></span><span>Fields<strong>{{ output.fields }}</strong></span><span>Charts<strong>{{ output.charts }}</strong></span><span>Missing<strong>{{ output.missing }}</strong></span></div><p>Dashboard generated from the active workbook, not placeholder data.</p></div><p v-else>Run the workflow after uploading a workbook. The result panel will show real rows, fields, missing values, and generated visualizations.</p></aside></div></section></template>
