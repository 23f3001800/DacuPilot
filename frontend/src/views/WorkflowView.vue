<script setup>
import { computed, onMounted, ref } from "vue";
import { streamWorkflow } from "../api";
import { getWorkbookThreadId, getWorkspaceStorageKey } from "../workbookSession.js";

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

function restoreLatestRun() {
  const runsKey = getWorkspaceStorageKey("insightpilot-workflow-runs", getWorkbookThreadId());
  try {
    const runs = JSON.parse(localStorage.getItem(runsKey) || "[]");
    if (!Array.isArray(runs) || !runs.length) return;
    output.value = runs[0];
    completed.value = true;
    stages.value.forEach((stage) => { stage.state = "done"; });
  } catch {
    output.value = null;
    completed.value = false;
  }
}

async function runWorkflow() {
  if (running.value) return;
  running.value = true; completed.value = false; output.value = null; error.value = "";
  stages.value.forEach((stage, index) => { stage.state = index === 0 ? "active" : "ready"; });
  try {
    const threadId = getWorkbookThreadId();
    await streamWorkflow({ threadId, onEvent(event) {
      if (event.event === "stage") {
        const map = { receive: 0, profile: 1, analysis: 2, response: 3 };
        const index = map[event.stage];
        if (index !== undefined) stages.value[index].state = event.state;
      }
      if (event.event === "result") {
        output.value = event.result;
        completed.value = true;
        const runsKey = getWorkspaceStorageKey("insightpilot-workflow-runs", threadId);
        try {
          const runs = JSON.parse(localStorage.getItem(runsKey) || "[]");
          const history = Array.isArray(runs) ? runs : [];
          localStorage.setItem(runsKey, JSON.stringify([{ ...event.result, id: crypto.randomUUID(), createdAt: new Date().toISOString() }, ...history].slice(0, 30)));
        } catch {
          error.value = "Workflow completed, but this browser could not save the result to local history.";
        }
        const chartsKey = getWorkspaceStorageKey("datapilot-generated-charts", threadId);
        try {
          const charts = JSON.parse(localStorage.getItem(chartsKey) || "[]");
          const history = Array.isArray(charts) ? charts : [];
          const newCharts = (event.result.chart_artifacts || []).map((chart) => ({ ...chart, generatedAt: new Date().toISOString() }));
          localStorage.setItem(chartsKey, JSON.stringify([...newCharts, ...history].slice(0, 50)));
        } catch {
          error.value = "Workflow completed, but this browser could not save chart references to local history.";
        }
      }
      if (event.event === "error") throw new Error(event.message || "Workflow execution failed.");
    }});
    if (!output.value) throw new Error("The workflow stream ended without returning a result. Run it again or check the backend logs.");
  } catch (caught) { error.value = caught.message; const activeStage = stages.value.find((stage) => stage.state === "active"); if (activeStage) activeStage.state = "error"; }
  finally { running.value = false; }
}

onMounted(restoreLatestRun);
</script>

<template><section class="product-page workflow-page"><div class="page-heading"><div><p class="eyebrow">Observable automation</p><h1>Agent Workflows</h1><p class="page-lead">Run a real workbook analysis and see the output produced by each stage.</p></div><span :class="['run-status', { running, completed }]" role="status"><i /> {{ status }}</span></div><div class="workflow-layout"><section class="panel workflow-card"><div class="workflow-card-head"><div><h2>Workbook analysis workflow</h2><p class="helper">Active session → profile → analyze → publish artifacts</p></div><button class="primary-button" :disabled="running" @click="runWorkflow">{{ running ? 'Running…' : completed ? 'Run again' : 'Run workflow' }} →</button></div><div class="workflow-steps"><div v-for="(stage, index) in stages" :key="stage.name" :class="['workflow-step', stage.state]"><span class="step-number">{{ stage.state === 'done' ? '✓' : stage.state === 'error' ? '!' : index + 1 }}</span><div><b>{{ stage.name }}</b><small>{{ stage.detail }}</small></div><span class="step-state">{{ stage.state === 'active' ? 'Working' : stage.state === 'done' ? 'Complete' : stage.state === 'error' ? 'Failed' : 'Waiting' }}</span></div></div><div v-if="error" class="workflow-error">{{ error }}</div></section><aside class="panel workflow-side"><span class="side-icon">✣</span><h2>Workflow output</h2><div v-if="output" class="workflow-output"><b>{{ output.filename }}</b><div><span>Rows<strong>{{ output.rows }}</strong></span><span>Fields<strong>{{ output.fields }}</strong></span><span>Charts<strong>{{ output.charts }}</strong></span><span>Missing<strong>{{ output.missing }}</strong></span></div><p>{{ output.summary }}</p><div v-if="output.chart_artifacts?.length" class="workflow-chart-list"><article v-for="chart in output.chart_artifacts" :key="chart.artifact_id"><img :src="chart.url" :alt="chart.title" /><b>{{ chart.title }}</b></article><p>These charts are saved in Dashboards and included in Reports.</p></div></div><p v-else>Run the workflow after uploading a workbook. Results and generated charts will come from the active workbook.</p></aside></div></section></template>
