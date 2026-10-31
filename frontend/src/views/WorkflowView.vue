<script setup>
import { computed, ref } from "vue";

const running = ref(false);
const completed = ref(false);
const stages = ref([
  { name: "Receive workbook", detail: "Wait for an uploaded Excel file", state: "ready" },
  { name: "Profile columns", detail: "Inspect types, missing values, and sheets", state: "ready" },
  { name: "Generate analysis", detail: "Create KPIs, trends, and evidence", state: "ready" },
  { name: "Prepare response", detail: "Return an explainable answer with metadata", state: "ready" },
]);
const status = computed(() => running.value ? "Agent is running" : completed.value ? "Workflow completed" : "Ready to run");
function runWorkflow() {
  if (running.value) return;
  completed.value = false; running.value = true;
  stages.value.forEach((stage, index) => { stage.state = index === 0 ? "active" : "ready"; });
  stages.value.forEach((stage, index) => setTimeout(() => { stage.state = "done"; if (stages.value[index + 1]) stages.value[index + 1].state = "active"; if (index === stages.value.length - 1) { running.value = false; completed.value = true; } }, 650 * (index + 1)));
}
</script>

<template><section class="product-page workflow-page"><div class="page-heading"><div><p class="eyebrow">Observable automation</p><h1>Agent Workflows</h1><p class="page-lead">Design a repeatable analysis run and watch every stage execute.</p></div><span :class="['run-status', { running, completed }]"><i /> {{ status }}</span></div><div class="workflow-layout"><section class="panel workflow-card"><div class="workflow-card-head"><div><h2>Workbook analysis workflow</h2><p class="helper">Upload → profile → analyze → explain</p></div><button class="primary-button" :disabled="running" @click="runWorkflow">{{ running ? 'Running…' : completed ? 'Run again' : 'Run workflow' }} →</button></div><div class="workflow-steps"><div v-for="(stage, index) in stages" :key="stage.name" :class="['workflow-step', stage.state]"><span class="step-number">{{ stage.state === 'done' ? '✓' : index + 1 }}</span><div><b>{{ stage.name }}</b><small>{{ stage.detail }}</small></div><span class="step-state">{{ stage.state === 'active' ? 'Working' : stage.state === 'done' ? 'Complete' : 'Waiting' }}</span></div></div></section><aside class="panel workflow-side"><span class="side-icon">✣</span><h2>What the agent does</h2><p>Each run is isolated to your active workbook session. The assistant exposes progress, tool activity, and answer quality after completion.</p><div class="workflow-stat"><span>Execution mode</span><b>Observable + explainable</b></div><div class="workflow-stat"><span>Output</span><b>Dashboard, answer, audit trail</b></div></aside></div></section></template>
