<script setup>
import { onMounted, ref } from "vue";
import { getWorkbookDashboard, getWorkbookPreview, getWorkbookSchema, streamAssistant, uploadWorkbook } from "../api";

const schema = ref(null);
const file = ref(null);
const uploadStatus = ref("");
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
  if (!message || sending.value || !assistantEnabled.value) return;
  question.value = "";
  messages.value.push({ role: "user", text: message });
  messages.value.push({ role: "assistant", text: "", thinking: true, citations: [], confidence: null, latencyMs: null });
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
          evaluation.value = event.payload?.evaluation_metrics || event.evaluation_metrics || event;
          current.confidence = evaluation.value.confidence_score ?? evaluation.value.confidence;
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
    current.thinking = false;
    current.latencyMs = elapsedMs.value;
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
        <button class="primary-button" :disabled="!file" @click="ingestWorkbook">Upload workbook</button>
        <p v-if="uploadStatus" class="helper">{{ uploadStatus }}</p>
        <div v-if="schema?.columns?.length" class="schema-list">
          <h3>Columns</h3>
          <span v-for="column in schema.columns" :key="column" class="schema-chip">{{ column }}</span>
        </div>
        <p v-else class="helper">No workbook schema loaded yet.</p>
        <section v-if="preview?.loaded" class="workbook-preview">
          <div class="panel-heading"><div><h2>Excel sheet</h2><p class="helper">Live read-only view of the active worksheet.</p></div><span class="preview-count">{{ preview.total_rows }} rows</span></div>
          <div class="table-scroll excel-table"><table><thead><tr><th class="row-number">#</th><th v-for="column in preview.columns" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="(row, index) in preview.rows" :key="index"><td class="row-number">{{ index + 1 }}</td><td v-for="column in preview.columns" :key="column">{{ row[column] ?? "" }}</td></tr></tbody></table></div>
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
            <div v-if="message.role === 'assistant' && !message.thinking && message.latencyMs !== null" class="answer-meta"><span class="latency">Latency {{ message.latencyMs }} ms</span><span v-if="message.confidence !== null">Confidence {{ Math.round(Number(message.confidence) * 100) }}%</span><span v-if="message.citations?.length">{{ message.citations.length }} citation{{ message.citations.length === 1 ? '' : 's' }}</span></div>
            <div v-if="message.citations?.length" class="citations"><span v-for="(citation, citeIndex) in message.citations" :key="citeIndex">{{ citation.title || citation.source || citation }}</span></div>
          </div>
        </div>
        <form class="question-form" @submit.prevent="ask()">
          <input v-model="question" placeholder="Ask anything about your data..." :disabled="sending || !assistantEnabled" />
          <span v-if="sending" class="live-latency">{{ elapsedMs }} ms</span>
          <button class="primary-button" type="submit" :disabled="sending || !question.trim() || !assistantEnabled">Send</button>
        </form>
        <div v-if="evaluation && !sending" class="evaluation-card"><strong>Answer quality</strong><span>Confidence: {{ Math.round(Number(evaluation.confidence_score ?? evaluation.confidence ?? 0) * 100) }}%</span><span v-if="citations.length">{{ citations.length }} citations</span></div>
      </section>
    </div>
  </section>
</template>
