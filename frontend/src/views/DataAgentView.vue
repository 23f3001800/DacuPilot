<script setup>
import { onMounted, ref } from "vue";
import { applyColumnOperation, getWorkbookDashboard, getWorkbookPreview, getWorkbookSchema, previewColumnOperation, streamAssistant, uploadWorkbook } from "../api";

const schema = ref(null);
const file = ref(null);
const uploadStatus = ref("");
const question = ref("");
const sending = ref(false);
const messages = ref([]);
const evaluation = ref(null);
const status = ref("");
const threadId = ref(sessionStorage.getItem("datapilot-thread-id") || crypto.randomUUID());
const preview = ref(null);
const dashboard = ref(null);
const columnName = ref("");
const formula = ref("");
const operationPreview = ref(null);
const operationStatus = ref("");

const prompts = [
  "Summarize the uploaded workbook.",
  "Which columns have missing values?",
  "Show the most important trends in this data.",
];

async function loadSchema() {
  try {
    schema.value = await getWorkbookSchema(threadId.value);
    preview.value = await getWorkbookPreview(threadId.value);
    dashboard.value = await getWorkbookDashboard(threadId.value);
  } catch {
    schema.value = null;
  }
}

function selectFile(event) {
  file.value = event.target.files?.[0] || null;
}

async function ingestWorkbook() {
  if (!file.value) return;
  uploadStatus.value = "Uploading workbook...";
  try {
    await uploadWorkbook(file.value, threadId.value);
    uploadStatus.value = "Workbook uploaded.";
    await loadSchema();
  } catch (error) {
    uploadStatus.value = error.message;
  }
}

async function ask(text = question.value) {
  const message = text.trim();
  if (!message || sending.value) return;
  question.value = "";
  messages.value.push({ role: "user", text: message });
  messages.value.push({ role: "assistant", text: "" });
  sending.value = true;
  status.value = "Starting analysis...";
  evaluation.value = null;

  try {
    await streamAssistant({
      message,
      threadId: threadId.value,
      onEvent(event) {
        if (event.event === "token") messages.value.at(-1).text += event.text || "";
        if (event.event === "status" || event.event === "tool_start") status.value = event.text || (event.tool ? "Running " + event.tool + "..." : "");
        if (event.event === "final_answer") messages.value.at(-1).text = event.text || messages.value.at(-1).text;
        if (event.event === "evaluation" || event.event === "metrics_evaluation") evaluation.value = event;
        if (event.thread_id) {
          threadId.value = event.thread_id;
          sessionStorage.setItem("datapilot-thread-id", event.thread_id);
        }
      },
    });
  } catch (error) {
    messages.value.at(-1).text = error.message;
  } finally {
    sending.value = false;
    status.value = "";
  }
}

async function previewColumn() {
  operationStatus.value = "Validating column operation...";
  try {
    operationPreview.value = await previewColumnOperation({ threadId: threadId.value, columnName: columnName.value, formula: formula.value });
    operationStatus.value = "Preview ready. Confirm to create a new workbook version.";
  } catch (error) {
    operationStatus.value = error.message;
    operationPreview.value = null;
  }
}

async function applyColumn() {
  if (!operationPreview.value) return;
  operationStatus.value = "Creating versioned workbook...";
  try {
    await applyColumnOperation({ threadId: threadId.value, operationId: operationPreview.value.operation_id });
    operationStatus.value = "New workbook version created.";
    operationPreview.value = null;
    await loadSchema();
  } catch (error) {
    operationStatus.value = error.message;
  }
}

onMounted(loadSchema);
</script>

<template>
  <section class="workflow-view">
    <div class="view-heading">
      <div>
        <p class="eyebrow">Workbook analysis</p>
        <h1>Data Agent</h1>
        <p>Upload a workbook, inspect its schema, and ask questions with streamed responses.</p>
      </div>
      <span v-if="status" class="status-pill">{{ status }}</span>
    </div>

    <div v-if="dashboard?.loaded" class="dashboard-strip">
      <div v-for="kpi in dashboard.kpis" :key="kpi.label" class="dashboard-kpi"><span>{{ kpi.label }}</span><strong>{{ kpi.value }}</strong></div>
    </div>
    <div v-if="dashboard?.charts?.length" class="chart-grid">
      <section v-for="chart in dashboard.charts" :key="chart.title" class="panel mini-chart"><h2>{{ chart.title }}</h2><div class="chart-bars"><i v-for="(value, index) in chart.series[0].values" :key="index" :style="{ height: `${Math.max(8, Math.min(100, Number(value) || 0))}%` }" /></div></section>
    </div>
    <section v-if="preview?.loaded" class="panel workbook-preview">
      <div class="panel-heading"><div><h2>Workbook preview</h2><p class="helper">Read-only preview of the active dataset.</p></div><span class="preview-count">{{ preview.total_rows }} rows</span></div>
      <div class="table-scroll"><table><thead><tr><th v-for="column in preview.columns" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="(row, index) in preview.rows" :key="index"><td v-for="column in preview.columns" :key="column">{{ row[column] ?? "-" }}</td></tr></tbody></table></div>
    </section>
    <div class="agent-grid">
      <section class="panel">
        <h2>Workbook</h2>
        <input type="file" accept=".xlsx,.xlsm" @change="selectFile" />
        <button class="primary-button" :disabled="!file" @click="ingestWorkbook">Upload workbook</button>
        <p v-if="uploadStatus" class="helper">{{ uploadStatus }}</p>
        <div v-if="schema?.columns?.length" class="schema-list">
          <h3>Columns</h3>
          <span v-for="column in schema.columns" :key="column" class="schema-chip">{{ column }}</span>
        </div>
        <p v-else class="helper">No workbook schema loaded yet.</p>
        <hr class="panel-rule" />
        <h2>Add a calculated column</h2>
        <p class="helper">Preview first; applying creates a new workbook version.</p>
        <input v-model="columnName" class="text-input" placeholder="Column name, e.g. Profit Margin" />
        <input v-model="formula" class="text-input" placeholder='Formula, e.g. df["Profit"] / df["Revenue"]' />
        <button class="secondary-button" :disabled="!columnName || !formula" @click="previewColumn">Preview column</button>
        <p v-if="operationStatus" class="helper">{{ operationStatus }}</p>
        <div v-if="operationPreview" class="operation-preview">
          <strong>{{ operationPreview.column_name }}</strong><span>{{ operationPreview.formula }}</span>
          <button class="primary-button" @click="applyColumn">Confirm and create version</button>
        </div>
      </section>

      <section class="panel chat-panel">
        <h2>Ask the agent</h2>
        <div class="prompt-row">
          <button v-for="prompt in prompts" :key="prompt" class="prompt-button" @click="ask(prompt)">{{ prompt }}</button>
        </div>
        <div class="message-list" aria-live="polite">
          <p v-if="!messages.length" class="helper">Your conversation will appear here.</p>
          <div v-for="(message, index) in messages" :key="index" :class="['message', message.role]">
            <strong>{{ message.role === "user" ? "You" : "Data Agent" }}</strong>
            <p>{{ message.text }}</p>
          </div>
        </div>
        <form class="question-form" @submit.prevent="ask()">
          <input v-model="question" placeholder="Ask a question about the workbook..." :disabled="sending" />
          <button class="primary-button" type="submit" :disabled="sending || !question.trim()">Send</button>
        </form>
        <div v-if="evaluation" class="evaluation-card">
          <strong>Evaluation</strong>
          <span>Confidence: {{ evaluation.confidence_score ?? evaluation.payload?.evaluation_metrics?.confidence_score ?? "n/a" }}</span>
        </div>
      </section>
    </div>
  </section>
</template>
