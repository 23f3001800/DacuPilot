<script setup>
import { onMounted, ref } from "vue";
import { deleteWorkbook, generateWorkbookChart, getWorkbookDashboard, getWorkbookDownloadUrl, getWorkbookPreview, getWorkbookSchema, streamAssistant, uploadWorkbook } from "../api";

const schema = ref(null);
const file = ref(null);
const uploadStatus = ref("");
const consentGiven = ref(false);
const refreshing = ref(false);
const question = ref("");
const sending = ref(false);
const messages = ref([]);
const evaluation = ref(null);
const citations = ref([]);
const assistantEnabled = ref(true);
const elapsedMs = ref(0);
const thinkingSteps = ref([]);
let latencyTimer;
const status = ref("");
const threadId = ref(sessionStorage.getItem("datapilot-thread-id") || crypto.randomUUID());
const preview = ref(null);
const dashboard = ref(null);

const prompts = [
  "Summarize the uploaded workbook.",
  "Which columns have missing values?",
  "Show the most important trends in this data.",
];

function chartPoints(chart) {
  const values = chart?.series?.[0]?.values || chart?.values || [];
  if (!values.length) return "";
  const max = Math.max(...values.map(Number));
  const min = Math.min(...values.map(Number));
  const range = max - min || 1;
  return values.map((value, index) => `${(index / Math.max(1, values.length - 1)) * 100},${96 - ((Number(value) - min) / range) * 82}`).join(" ");
}

function excelColumnLabel(index) {
  let label = "";
  let value = index + 1;
  while (value) { const remainder = (value - 1) % 26; label = String.fromCharCode(65 + remainder) + label; value = Math.floor((value - 1) / 26); }
  return label;
}

function confidencePercent(value) {
  const score = Number(value);
  if (!Number.isFinite(score)) return "n/a";
  return `${Math.round((score <= 1 ? score : score / 100) * 100)}%`;
}

async function loadSchema() {
  try {
    schema.value = await getWorkbookSchema(threadId.value);
    preview.value = await getWorkbookPreview(threadId.value);
    dashboard.value = await getWorkbookDashboard(threadId.value);
  } catch {
    schema.value = null;
  }
}

async function refreshWorkbook() {
  refreshing.value = true;
  try { await loadSchema(); uploadStatus.value = "Workbook view refreshed."; }
  finally { refreshing.value = false; }
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

async function removeWorkbook() {
  if (!schema.value || !confirm("Delete the saved workbook from this session?")) return;
  try {
    await deleteWorkbook(threadId.value);
    schema.value = null;
    preview.value = null;
    dashboard.value = null;
    uploadStatus.value = "Workbook deleted.";
    messages.value.push({ role: "assistant", text: "The saved workbook was deleted from this session." });
  } catch (error) { uploadStatus.value = error.message; }
}

async function ask(text = question.value) {
  const message = text.trim();
  if (!message || sending.value || !assistantEnabled.value) return;
  question.value = "";
  messages.value.push({ role: "user", text: message });
  const wantsChart = /chart|graph|plot|visual|trend/i.test(message);
  messages.value.push({ role: "assistant", text: "", thinking: true, citations: [], confidence: null, latencyMs: null, chart: null });
  sending.value = true;
  status.value = "Starting analysis...";
  evaluation.value = null;
  citations.value = [];
  thinkingSteps.value = ["Understanding your request"];
  const startedAt = performance.now();
  elapsedMs.value = 0;
  clearInterval(latencyTimer);
  latencyTimer = setInterval(() => { elapsedMs.value = Math.round(performance.now() - startedAt); }, 100);

  try {
    await streamAssistant({
      message,
      threadId: threadId.value,
      onEvent(event) {
        const current = messages.value.at(-1);
        if (event.event === "token") current.text += event.text || "";
        if (event.event === "status" || event.event === "tool_start") {
          status.value = event.text || (event.tool ? "Running " + event.tool + "..." : "Working...");
          thinkingSteps.value.push(status.value);
        }
        if (event.event === "final_answer") current.text = event.text || current.text;
        if (event.event === "evaluation" || event.event === "metrics_evaluation") {
          const metrics = event.payload?.evaluation_metrics || event.payload?.metrics || event.evaluation_metrics || {};
          const score = event.confidence_score ?? metrics.confidence_score ?? event.payload?.confidence_score ?? event.confidence;
          evaluation.value = { ...metrics, confidence_score: score };
          current.confidence = score;
        }
        if (event.event === "citation" || event.event === "citations") {
          const incoming = event.citations || event.payload?.citations || [];
          citations.value = Array.isArray(incoming) ? incoming : [incoming];
          current.citations = citations.value;
        }
        if (event.thread_id) {
          threadId.value = event.thread_id;
          sessionStorage.setItem("datapilot-thread-id", event.thread_id);
        }
      },
    });
  } catch (error) {
    messages.value.at(-1).text = error.message;
  } finally {
    clearInterval(latencyTimer);
    elapsedMs.value = Math.round(performance.now() - startedAt);
    const current = messages.value.at(-1);
    if (wantsChart) {
      try { current.chart = await generateWorkbookChart(threadId.value); } catch { current.chart = null; }
    }
    if (wantsChart && current.chart) {
      current.text = current.text.replace(/```[\s\S]*?```/g, "").replace(/I couldn’t render an image in this environment, but I can \(and did\) prepare the data and can give you ready-to-run code to produce a trend chart locally\./gi, "Chart generated from the uploaded workbook:").trim();
      const existing = JSON.parse(sessionStorage.getItem("datapilot-generated-charts") || "[]");
      sessionStorage.setItem("datapilot-generated-charts", JSON.stringify([...existing, { ...current.chart, generatedAt: new Date().toISOString() }].slice(-12)));
    }
    current.thinking = false;
    current.latencyMs = elapsedMs.value;
    if (/(add|create|modify|update).*(column|workbook)/i.test(message)) await refreshWorkbook();
    sending.value = false;
    status.value = "";
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

    <div class="studio-layout" :class="{ 'assistant-collapsed': !assistantEnabled }">
      <section class="panel workbook-panel">
        <h2>Workbook</h2>
        <input type="file" accept=".xlsx,.xlsm" @change="selectFile" />
        <label class="consent-row workbook-consent"><input v-model="consentGiven" type="checkbox" /> I consent to sending workbook content to the configured AI provider when I ask the agent to analyze it.</label>
        <button class="primary-button" :disabled="!file || !consentGiven" @click="ingestWorkbook">Upload workbook</button>
        <p v-if="uploadStatus" class="helper">{{ uploadStatus }}</p>
        <div v-if="schema?.loaded" class="workbook-actions"><a class="secondary-button" :href="getWorkbookDownloadUrl(threadId)" download>Save Excel file</a><button class="danger-button" type="button" @click="removeWorkbook">Delete workbook</button></div>
        <div v-if="schema?.columns?.length" class="schema-list">
          <h3>Columns</h3>
          <span v-for="column in schema.columns" :key="column" class="schema-chip">{{ column }}</span>
        </div>
        <p v-else class="helper">No workbook schema loaded yet.</p>
        <section v-if="preview?.loaded" class="workbook-preview">
          <div class="panel-heading"><div><h2>{{ schema.selected_sheet || "Excel sheet" }}</h2><p class="helper">{{ schema.filename }} · live workbook view</p></div><div class="sheet-actions"><span class="preview-count">{{ preview.total_rows }} rows</span><button class="refresh-button" type="button" :disabled="refreshing" @click="refreshWorkbook">↻ {{ refreshing ? "Refreshing" : "Refresh" }}</button></div></div>
          <div class="table-scroll excel-table"><table><thead><tr class="column-letters"><th class="row-number"></th><th v-for="(column, columnIndex) in preview.columns" :key="column">{{ excelColumnLabel(columnIndex) }}</th></tr><tr><th class="row-number">#</th><th v-for="column in preview.columns" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="(row, index) in preview.rows" :key="index"><td class="row-number">{{ index + 1 }}</td><td v-for="column in preview.columns" :key="column">{{ row[column] ?? "" }}</td></tr></tbody></table></div>
        </section>
        <div v-if="dashboard?.loaded" class="workbook-kpis"><div v-for="kpi in dashboard.kpis" :key="kpi.label"><span>{{ kpi.label }}</span><b>{{ kpi.value }}</b></div></div>
      </section>

      <section class="panel chat-panel">
        <div class="assistant-heading">
          <div class="assistant-title"><span class="assistant-orb">✦</span><div><h2>DataPilot Assistant</h2><span class="assistant-online"><i /> {{ assistantEnabled ? 'Online' : 'Paused' }}</span></div></div>
          <button class="assistant-toggle" :class="{ on: assistantEnabled }" type="button" @click="assistantEnabled = !assistantEnabled"><i /> {{ assistantEnabled ? 'Assistant on' : 'Assistant off' }}</button>
        </div>
        <div v-if="!assistantEnabled" class="assistant-offline">Assistant is paused. Turn the toggle on to ask questions.</div>
        <div class="prompt-row">
          <button v-for="prompt in prompts" :key="prompt" class="prompt-button" :disabled="!assistantEnabled" @click="ask(prompt)">{{ prompt }}</button>
        </div>
        <div class="message-list" aria-live="polite">
          <p v-if="!messages.length" class="helper">Your conversation will appear here.</p>
          <div v-for="(message, index) in messages" :key="index" :class="['message', message.role]">
            <strong>{{ message.role === "user" ? "You" : "DataPilot Assistant" }}</strong>
            <div v-if="message.role === 'assistant' && message.thinking" class="thinking"><span /><span /><span /> {{ status || 'Thinking through your workbook...' }}<b class="thinking-latency">{{ sending ? elapsedMs : 0 }} ms</b></div>
            <p v-if="message.text">{{ message.text }}</p>
            <div v-if="message.chart" class="chat-chart"><div class="chat-chart-title"><b>{{ message.chart.title }}</b><span>Generated from workbook data</span></div><svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline :points="chartPoints(message.chart)" /></svg></div>
            <div v-if="message.role === 'assistant' && !message.thinking && message.latencyMs !== null" class="answer-meta"><span class="latency">Latency {{ message.latencyMs }} ms</span><span v-if="message.confidence !== null && message.confidence !== undefined">Confidence {{ confidencePercent(message.confidence) }}</span><span v-if="message.citations?.length">{{ message.citations.length }} citation{{ message.citations.length === 1 ? '' : 's' }}</span></div>
            <div v-if="message.citations?.length" class="citations"><span v-for="(citation, citeIndex) in message.citations" :key="citeIndex">{{ citation.title || citation.source || citation }}</span></div>
          </div>
        </div>
        <form class="question-form" @submit.prevent="ask()">
          <input v-model="question" placeholder="Ask anything about your data..." :disabled="sending || !assistantEnabled" />
          <span v-if="sending" class="live-latency">{{ elapsedMs }} ms</span>
          <button class="primary-button" type="submit" :disabled="sending || !question.trim() || !assistantEnabled">Send</button>
        </form>
        <div v-if="evaluation && !sending && evaluation.confidence_score !== undefined" class="evaluation-card"><strong>Answer quality</strong><span>Confidence: {{ confidencePercent(evaluation.confidence_score) }}</span><span v-if="citations.length">{{ citations.length }} citations</span></div>
      </section>
    </div>
  </section>
</template>
