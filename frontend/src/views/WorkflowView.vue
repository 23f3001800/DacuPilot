<script setup>
import { computed, ref } from "vue";
import { streamWorkflow } from "../api";

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
async function runWorkflow() {
  if (running.value) return;
  running.value = true; completed.value = false; output.value = null; error.value = "";
  stages.value.forEach((stage, index) => { stage.state = index === 0 ? "active" : "ready"; });
  try {
    const threadId = sessionStorage.getItem("datapilot-thread-id") || "default";
    await streamWorkflow({ threadId, onEvent(event) {
      if (event.event === "stage") {
        const map = { receive: 0, profile: 1, analysis: 2, response: 3 };
        const index = map[event.stage];
        if (index !== undefined) stages.value[index].state = event.state;
      }
      if (event.event === "result") {
        output.value = event.result;
        completed.value = true;
        const runs = JSON.parse(localStorage.getItem("insightpilot-workflow-runs") || "[]");
        localStorage.setItem("insightpilot-workflow-runs", JSON.stringify([{ ...event.result, id: crypto.randomUUID(), createdAt: new Date().toISOString() }, ...runs].slice(0, 30)));
      }
      if (event.event === "error") throw new Error(event.message || "Workflow execution failed.");
    }});
  } catch (caught) { error.value = caught.message; const activeStage = stages.value.find((stage) => stage.state === "active"); if (activeStage) activeStage.state = "error"; }
  finally { running.value = false; }
}
</script>

<template><section class="product-page workflow-page"><div class="page-heading"><div><p class="eyebrow">Observable automation</p><h1>Agent Workflows</h1><p class="page-lead">Run a real workbook analysis and see the output produced by each stage.</p></div><span :class="['run-status', { running, completed }]"><i /> {{ status }}</span></div><div class="workflow-layout"><section class="panel workflow-card"><div class="workflow-card-head"><div><h2>Workbook analysis workflow</h2><p class="helper">Active session → profile → dashboard → result</p></div><button class="primary-button" :disabled="running" @click="runWorkflow">{{ running ? 'Running…' : completed ? 'Run again' : 'Run workflow' }} →</button></div><div class="workflow-steps"><div v-for="(stage, index) in stages" :key="stage.name" :class="['workflow-step', stage.state]"><span class="step-number">{{ stage.state === 'done' ? '✓' : stage.state === 'error' ? '!' : index + 1 }}</span><div><b>{{ stage.name }}</b><small>{{ stage.detail }}</small></div><span class="step-state">{{ stage.state === 'active' ? 'Working' : stage.state === 'done' ? 'Complete' : stage.state === 'error' ? 'Failed' : 'Waiting' }}</span></div></div><div v-if="error" class="workflow-error">{{ error }}</div></section><aside class="panel workflow-side"><span class="side-icon">✣</span><h2>Workflow output</h2><div v-if="output" class="workflow-output"><b>{{ output.filename }}</b><div><span>Rows<strong>{{ output.rows }}</strong></span><span>Fields<strong>{{ output.fields }}</strong></span><span>Charts<strong>{{ output.charts }}</strong></span><span>Missing<strong>{{ output.missing }}</strong></span></div><p>Dashboard generated from the active workbook, not placeholder data.</p></div><p v-else>Run the workflow after uploading a workbook. The result panel will show real rows, fields, missing values, and generated visualizations.</p></aside></div></section></template>
