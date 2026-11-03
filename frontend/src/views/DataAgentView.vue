<script setup>
import { onMounted, ref, watch } from "vue";
import { applyColumnOperation, deleteWorkbook, generateWorkbookChart, getWorkbookDashboard, getWorkbookDownloadUrl, getWorkbookPreview, getWorkbookSchema, selectWorkbookSheet, streamAssistant, uploadWorkbook } from "../api";
import { preferences } from "../preferences.js";
import { getWorkbookThreadId, getWorkspaceStorageKey } from "../workbookSession.js";

const props = defineProps({ initialQuestion: { type: String, default: "" } });
const emit = defineEmits(["clear-initial"]);
const schema = ref(null);
const file = ref(null);
const workbookFileInput = ref(null);
const uploading = ref(false);
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
const threadId = ref(getWorkbookThreadId());
const preview = ref(null);
const previewOffset = ref(0);
const previewLimit = 50;
const dashboard = ref(null);
const workbookTab = ref("data");
const cleaningPreview = ref(null);
const cleaningBusy = ref(false);
const workbookHistory = ref([]);
const canUndo = ref(false);

watch(() => props.initialQuestion, (value) => {
  if (value) question.value = value;
}, { immediate: true });

async function undoWorkbookChange() {
  const response = await fetch(`/api/data/history/undo?thread_id=${encodeURIComponent(threadId.value)}`, { method: "POST" });
  if (!response.ok) { uploadStatus.value = (await response.json()).detail || "Could not restore previous version."; return; }
  const restored = await response.json();
  uploadStatus.value = `Restored ${restored.filename}.`;
  await loadSchema();
}

async function previewCleaning(operation) {
  cleaningBusy.value = true;
  try {
    const response = await fetch("/api/data/cleaning/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ thread_id: threadId.value, operation }) });
    if (!response.ok) throw new Error((await response.json()).detail || "Could not preview cleaning operation.");
    cleaningPreview.value = await response.json();
  } catch (error) { uploadStatus.value = error.message; }
  finally { cleaningBusy.value = false; }
}

async function applyCleaning() {
  if (!cleaningPreview.value) return;
  cleaningBusy.value = true;
  try {
    const operation = cleaningPreview.value.operation;
    const response = await fetch("/api/data/cleaning/apply", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ thread_id: threadId.value, operation, operation_id: cleaningPreview.value.operation_id }) });
    if (!response.ok) throw new Error((await response.json()).detail || "Could not apply cleaning operation.");
    const result = await response.json();
    cleaningPreview.value = null;
    uploadStatus.value = `Applied cleaning. Saved new workbook version ${result.filename}.`;
    await loadSchema();
  } catch (error) { uploadStatus.value = error.message; }
  finally { cleaningBusy.value = false; }
}

function missingFor(column) {
  return preview.value?.rows?.filter((row) => row[column] === null || row[column] === undefined || row[column] === "").length ?? 0;
}

function uniqueFor(column) {
  return new Set((preview.value?.rows || []).map((row) => String(row[column] ?? ""))).size;
}

const prompts = [
  "Summarize the uploaded workbook.",
  "Which columns have missing values?",
  "Show a useful chart from this data.",
];

function chartSpecFor(message) {
  const normalizedMessage = message.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const normalize = (value) => String(value).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const columns = schema.value?.columns || [];
  const numericColumns = columns.filter((column) => {
    const semantic = schema.value?.semantic_types?.[column] || "";
    const dtype = schema.value?.data_types?.[column] || "";
    return ["number", "currency", "numeric text"].includes(semantic) || /int|float|decimal|double|numeric/i.test(dtype);
  });
  const requestedMetric = numericColumns
    .filter((column) => normalizedMessage.includes(normalize(column)))
    .sort((left, right) => normalize(right).length - normalize(left).length)[0];
  const metric = requestedMetric || numericColumns[0] || null;
  const categories = columns.filter((column) => column !== metric && !numericColumns.includes(column));
  const requestedCategory = categories
    .filter((column) => normalizedMessage.includes(normalize(column)))
    .sort((left, right) => normalize(right).length - normalize(left).length)[0];
  const category = requestedCategory || categories.find((column) => ["date", "date text", "category"].includes(schema.value?.semantic_types?.[column])) || null;
  return { metric, category };
}

function excelColumnLabel(index) {
  let label = "";
  let value = index + 1;
  while (value) { const remainder = (value - 1) % 26; label = String.fromCharCode(65 + remainder) + label; value = Math.floor((value - 1) / 26); }
  return label;
}

function confidencePercent(value) {
  if (value === null || value === undefined || value === "") return "Not scored";
  const score = Number(value);
  if (!Number.isFinite(score)) return "n/a";
  return `${Math.round((score <= 1 ? score : score / 100) * 100)}%`;
}

async function loadSchema() {
  try {
    schema.value = await getWorkbookSchema(threadId.value);
    const lastPageOffset = Math.max(0, Math.floor((Number(schema.value.total_rows || 1) - 1) / previewLimit) * previewLimit);
    previewOffset.value = Math.min(previewOffset.value, lastPageOffset);
    preview.value = await getWorkbookPreview(threadId.value, previewOffset.value, previewLimit);
    dashboard.value = await getWorkbookDashboard(threadId.value);
    try {
      const response = await fetch(`/api/data/history?thread_id=${encodeURIComponent(threadId.value)}`);
      const history = response.ok ? await response.json() : { can_undo: false, versions: [] };
      canUndo.value = Boolean(history.can_undo);
      workbookHistory.value = history.versions || [];
    } catch { canUndo.value = false; workbookHistory.value = []; }
  } catch {
    schema.value = null;
  }
}

async function refreshWorkbook() {
  refreshing.value = true;
  try { await loadSchema(); uploadStatus.value = "Workbook view refreshed."; }
  finally { refreshing.value = false; }
}

async function setPreviewOffset(offset) {
  if (refreshing.value || !preview.value) return;
  const maxOffset = Math.max(0, Math.floor((preview.value.total_rows - 1) / previewLimit) * previewLimit);
  previewOffset.value = Math.min(maxOffset, Math.max(0, offset));
  refreshing.value = true;
  try { preview.value = await getWorkbookPreview(threadId.value, previewOffset.value, previewLimit); }
  catch (error) { uploadStatus.value = error.message; }
  finally { refreshing.value = false; }
}

async function selectSheet(sheetName) {
  if (!sheetName || sheetName === schema.value?.selected_sheet || refreshing.value) return;
  refreshing.value = true;
  try {
    await selectWorkbookSheet(threadId.value, sheetName);
    previewOffset.value = 0;
    await loadSchema();
    uploadStatus.value = `Showing worksheet ${sheetName}.`;
  } catch (error) { uploadStatus.value = error.message; }
  finally { refreshing.value = false; }
}

async function applyChatColumnChange(message) {
  if (!message.changePreview || message.applyingChange) return;
  message.applyingChange = true;
  message.changeError = "";
  try {
    const result = await applyColumnOperation({ threadId: threadId.value, operationId: message.changePreview.operation_id });
    message.changePreview = null;
    message.changeApplied = true;
    const action = { add: "Added", update: "Updated", delete: "Deleted" }[result.operation] || "Changed";
    message.changeAppliedText = `${action} column ${result.column_name} and saved the new workbook version.`;
    uploadStatus.value = `${action} ${result.column_name}. Saved workbook version ${result.filename}.`;
    await loadSchema();
  } catch (error) {
    message.changeError = error.message;
  } finally {
    message.applyingChange = false;
  }
}

function selectFile(event) {
  file.value = event.target.files?.[0] || null;
  if (file.value) void ingestWorkbook();
}

function openFilePicker() {
  if (!uploading.value && !sending.value) workbookFileInput.value?.click();
}

async function ingestWorkbook() {
  if (!file.value || uploading.value || sending.value) return;
  uploading.value = true;
  uploadStatus.value = "Uploading workbook...";
  try {
    const replacingWorkbook = Boolean(schema.value?.loaded);
    await uploadWorkbook(file.value, threadId.value);
    if (replacingWorkbook) {
      localStorage.removeItem(getWorkspaceStorageKey("insightpilot-analyses", threadId.value));
      localStorage.removeItem(getWorkspaceStorageKey("datapilot-generated-charts", threadId.value));
      localStorage.removeItem(getWorkspaceStorageKey("insightpilot-workflow-runs", threadId.value));
      consentGiven.value = false;
      evaluation.value = null;
      citations.value = [];
      messages.value = [{ role: "assistant", text: "A new workbook was uploaded. Review and confirm workbook-processing consent before asking the Data Analysis Agent to analyze it." }];
    }
    file.value = null;
    if (workbookFileInput.value) workbookFileInput.value.value = "";
    previewOffset.value = 0;
    uploadStatus.value = "Workbook uploaded.";
    await loadSchema();
  } catch (error) {
    uploadStatus.value = error.message;
    file.value = null;
    if (workbookFileInput.value) workbookFileInput.value.value = "";
  } finally {
    uploading.value = false;
  }
}

async function removeWorkbook() {
  if (!schema.value || sending.value || uploading.value || !confirm("Delete the saved workbook from this session?")) return;
  try {
    await deleteWorkbook(threadId.value);
    schema.value = null;
    preview.value = null;
    dashboard.value = null;
    localStorage.removeItem(getWorkspaceStorageKey("datapilot-generated-charts", threadId.value));
    localStorage.removeItem(getWorkspaceStorageKey("insightpilot-analyses", threadId.value));
    localStorage.removeItem(getWorkspaceStorageKey("insightpilot-workflow-runs", threadId.value));
    uploadStatus.value = "Workbook deleted.";
    consentGiven.value = false;
    evaluation.value = null;
    citations.value = [];
    messages.value = [{ role: "assistant", text: "The saved workbook and its saved analysis history were deleted from this session." }];
  } catch (error) { uploadStatus.value = error.message; }
}

async function ask(text = question.value) {
  const message = text.trim();
  if (!message || sending.value || !assistantEnabled.value) return;
  emit("clear-initial");
  if (!consentGiven.value) {
    messages.value.push({ role: "assistant", text: "Please confirm the workbook-processing consent above before asking the Data Analysis Agent to analyze this file." });
    return;
  }
  question.value = "";
  messages.value.push({ role: "user", text: message });
  const wantsChart = /chart|graph|plot|visual|trend|dashboard/i.test(message);
  messages.value.push({ role: "assistant", text: "", thinking: true, citations: [], confidence: null, latencyMs: null, chart: null });
  sending.value = true;
  status.value = "Starting analysis...";
  evaluation.value = null;
  citations.value = [];
  thinkingSteps.value = ["Understanding your request"];
  const startedAt = performance.now();
  let serverLatencyMs = null;
  let streamFailed = false;
  elapsedMs.value = 0;
  clearInterval(latencyTimer);
  latencyTimer = setInterval(() => { elapsedMs.value = Math.round(performance.now() - startedAt); }, 100);

  try {
    await streamAssistant({
      message,
      threadId: threadId.value,
      processingConsent: consentGiven.value,
      onEvent(event) {
        const current = messages.value.at(-1);
        if (event.event === "token") current.text += event.text || "";
        if (event.event === "status" || event.event === "tool_start") {
          status.value = event.text || (event.tool ? "Running " + event.tool + "..." : "Working...");
          thinkingSteps.value.push(status.value);
        }
        if (event.event === "final_answer") current.text = event.text || current.text;
        if (event.event === "latency" && Number.isFinite(Number(event.total_ms))) {
          serverLatencyMs = Number(event.total_ms);
          elapsedMs.value = Math.round(serverLatencyMs);
        }
        if (event.event === "error") {
          streamFailed = true;
          current.text = event.details || "The data analysis request failed. Please try again.";
        }
        if (event.event === "change_preview") current.changePreview = event.preview;
        if (event.event === "evaluation" || event.event === "metrics_evaluation") {
          const metrics = event.payload?.evaluation_metrics || event.payload?.metrics || event.payload || event.evaluation_metrics || {};
          const candidates = [event, metrics, event.payload || {}];
          const source = candidates.find((item) => Object.prototype.hasOwnProperty.call(item, "confidence_score"))
            || candidates.find((item) => Object.prototype.hasOwnProperty.call(item, "confidence"));
          const score = source ? (source.confidence_score ?? source.confidence ?? null) : null;
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
    streamFailed = true;
    messages.value.at(-1).text = error.message;
  } finally {
    clearInterval(latencyTimer);
    const current = messages.value.at(-1);
    elapsedMs.value = Math.round(serverLatencyMs ?? (performance.now() - startedAt));
    if (wantsChart && !streamFailed && schema.value?.loaded) {
      status.value = "Generating a chart from the active workbook…";
      thinkingSteps.value.push(status.value);
      const chartSpec = chartSpecFor(message);
      try { current.chart = await generateWorkbookChart(threadId.value, chartSpec.metric, chartSpec.category); }
      catch (error) {
        current.chart = null;
        current.text = current.text.replace(/```[\s\S]*?```/g, "").trim();
        current.text = `I could not generate a chart from this workbook: ${error.message}`;
      }
    }
    if (wantsChart && current.chart) {
      current.text = current.text.replace(/```[\s\S]*?```/g, "").replace(/I couldn’t render an image[\s\S]*?locally\./gi, "").trim();
      if (/I couldn’t complete that workbook operation|I couldn't complete that workbook operation/i.test(current.text)) {
        current.text = "The written calculation did not complete, so I can’t verify its totals. This chart was generated directly from the active workbook.";
      } else if (!current.text || /ready-to-run code|matplotlib|plot locally/i.test(current.text)) {
        current.text = "Generated this chart from the active workbook. It is also saved in Dashboards.";
      }
      let existing = [];
      const chartKey = getWorkspaceStorageKey("datapilot-generated-charts", threadId.value);
      try { existing = JSON.parse(localStorage.getItem(chartKey) || "[]"); } catch { existing = []; }
      localStorage.setItem(chartKey, JSON.stringify([...existing, { ...current.chart, generatedAt: new Date().toISOString() }].slice(-50)));
    }
    current.thinking = false;
    current.latencyMs = serverLatencyMs ?? elapsedMs.value;
    try {
      const analysisKey = getWorkspaceStorageKey("insightpilot-analyses", threadId.value);
      const savedAnalyses = JSON.parse(localStorage.getItem(analysisKey) || "[]");
      localStorage.setItem(analysisKey, JSON.stringify([{ id: crypto.randomUUID(), question: message, answer: current.text, confidence: current.confidence, citations: current.citations, latencyMs: current.latencyMs, createdAt: new Date().toISOString(), filename: schema.value?.filename, chart: current.chart }, ...savedAnalyses].slice(0, 50)));
    } catch { uploadStatus.value = "Could not save this analysis to browser history."; }
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
        <h1>Data Analysis Agent</h1>
        <p>Upload a workbook, inspect its schema, and ask questions with streamed responses.</p>
      </div>
      <span v-if="status && preferences.liveUpdates" class="status-pill">{{ status }}</span>
    </div>

    <div class="studio-layout" :class="{ 'assistant-collapsed': !assistantEnabled }">
      <section class="panel workbook-panel">
        <h2>Workbook</h2>
        <input ref="workbookFileInput" class="visually-hidden-file-input" type="file" accept=".xlsx,.xlsm" :disabled="uploading || sending" @change="selectFile" />
        <button class="primary-button" type="button" :disabled="uploading || sending" @click="openFilePicker">{{ uploading ? "Uploading…" : "Upload Excel workbook" }}</button>
        <p v-if="uploadStatus" class="helper">{{ uploadStatus }}</p>
          <div v-if="schema?.loaded" class="workbook-actions"><a class="secondary-button" :href="getWorkbookDownloadUrl(threadId)" download>Save Excel file</a><button class="danger-button" type="button" :disabled="sending || uploading" @click="removeWorkbook">Delete workbook</button></div>
        <div v-if="schema?.columns?.length" class="schema-list">
          <h3>Columns</h3>
          <span v-for="column in schema.columns" :key="column" class="schema-chip">{{ column }}</span>
        </div>
        <p v-else class="helper">No workbook schema loaded yet.</p>
        <section v-if="preview?.loaded" class="workbook-preview">
          <div class="panel-heading"><div><h2>{{ schema.selected_sheet || "Excel sheet" }}</h2><p class="helper">{{ schema.filename }} · live workbook view</p><label v-if="schema.sheet_names?.length > 1" class="sheet-select">Worksheet<select :value="schema.selected_sheet" :disabled="refreshing" @change="selectSheet($event.target.value)"><option v-for="sheet in schema.sheet_names" :key="sheet" :value="sheet">{{ sheet }}</option></select></label></div><div class="sheet-actions"><span class="preview-count">{{ preview.total_rows.toLocaleString() }} rows</span><span class="sheet-range">Rows {{ preview.rows.length ? preview.offset + 1 : 0 }}–{{ preview.offset + preview.rows.length }} of {{ preview.total_rows.toLocaleString() }}</span><button class="refresh-button" type="button" :disabled="refreshing || previewOffset === 0" @click="setPreviewOffset(previewOffset - previewLimit)">← Previous</button><button class="refresh-button" type="button" :disabled="refreshing || previewOffset + previewLimit >= preview.total_rows" @click="setPreviewOffset(previewOffset + previewLimit)">Next →</button><button class="refresh-button" type="button" :disabled="refreshing" @click="refreshWorkbook">↻ {{ refreshing ? "Refreshing" : "Refresh" }}</button></div></div>
          <nav class="workbook-tabs" aria-label="Workbook views"><button v-for="tab in ['data','profile','cleaning','schema','history']" :key="tab" :class="{ active: workbookTab === tab }" @click="workbookTab = tab">{{ tab }}</button></nav>
          <div v-if="workbookTab === 'data'" class="table-scroll excel-table" :class="{ compact: preferences.compactTables }"><table><thead><tr class="column-letters"><th class="row-number"></th><th v-for="(column, columnIndex) in preview.columns" :key="column">{{ excelColumnLabel(columnIndex) }}</th></tr><tr><th class="row-number">#</th><th v-for="column in preview.columns" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="(row, index) in preview.rows" :key="index"><td class="row-number">{{ preview.offset + index + 1 }}</td><td v-for="column in preview.columns" :key="column">{{ row[column] ?? "" }}</td></tr></tbody></table></div>
          <div v-else-if="workbookTab === 'profile'" class="profile-table-wrap"><table class="profile-table"><thead><tr><th>Field</th><th>Type</th><th>Preview rows</th><th>Unique</th><th>Missing</th></tr></thead><tbody><tr v-for="column in preview.columns" :key="column"><td>{{ column }}</td><td>{{ schema.data_types?.[column] || 'unknown' }}</td><td>{{ preview.rows.length }}</td><td>{{ uniqueFor(column) }}</td><td>{{ missingFor(column) }}</td></tr></tbody></table><p class="helper">Profile counts reflect the rows currently loaded in the preview ({{ preview.rows.length }} rows).</p></div>
          <div v-else-if="workbookTab === 'cleaning'" class="cleaning-workspace"><h3>Safe cleaning actions</h3><p class="helper">Preview the impact before applying. Applying saves a new workbook version.</p><div class="cleaning-buttons"><button class="secondary-button" :disabled="cleaningBusy" @click="previewCleaning('remove_duplicates')">Preview duplicate removal</button><button class="secondary-button" :disabled="cleaningBusy" @click="previewCleaning('drop_missing_rows')">Preview missing-row removal</button></div><div v-if="cleaningPreview" class="cleaning-preview"><b>{{ cleaningPreview.label }}</b><p>{{ cleaningPreview.rows_removed }} of {{ cleaningPreview.rows_before }} rows will be removed · {{ cleaningPreview.rows_after }} rows remain.</p><button class="primary-button" :disabled="cleaningBusy" @click="applyCleaning">{{ cleaningBusy ? 'Applying…' : 'Apply and save new version' }}</button></div></div>
          <div v-else-if="workbookTab === 'schema'" class="schema-detail"><div v-for="column in preview.columns" :key="column"><b>{{ column }}</b><span>{{ schema.data_types?.[column] || 'unknown' }}</span><small>{{ uniqueFor(column) }} unique preview values · {{ missingFor(column) }} missing in preview</small></div></div>
          <div v-else class="history-list"><div v-for="version in workbookHistory" :key="`${version.filename}-${version.created_at}`"><span>Restorable version</span><b>{{ version.filename }}</b><small>{{ version.operation }} · {{ version.created_at ? new Date(version.created_at).toLocaleString() : 'Earlier version' }}</small></div><p v-if="!workbookHistory.length" class="helper">No saved workbook changes yet. Column edits and cleaning operations create restorable versions.</p><button v-if="canUndo" class="secondary-button" @click="undoWorkbookChange">Undo latest workbook change</button><p v-else class="helper">No server-restorable earlier version is available.</p></div>
        </section>
        <div v-if="dashboard?.loaded" class="workbook-kpis"><div v-for="kpi in dashboard.kpis" :key="kpi.label"><span>{{ kpi.label }}</span><b>{{ kpi.value }}</b></div></div>
      </section>

      <section class="panel chat-panel">
        <div class="assistant-heading">
          <div class="assistant-title"><span class="assistant-orb">✦</span><div><h2>Data Analysis Agent</h2><span class="assistant-online"><i /> {{ assistantEnabled ? 'Online' : 'Paused' }}</span></div></div>
          <button class="assistant-toggle" :class="{ on: assistantEnabled }" type="button" :aria-label="assistantEnabled ? 'Pause Data Analysis Agent' : 'Enable Data Analysis Agent'" @click="assistantEnabled = !assistantEnabled"><i /> {{ assistantEnabled ? 'Data Agent on' : 'Data Agent off' }}</button>
        </div>
        <label class="consent-row workbook-consent" :class="{ 'consent-accepted': consentGiven }"><input v-model="consentGiven" type="checkbox" :disabled="sending" /><span><strong>Allow workbook analysis</strong><small>Required before InsightPilot Analyst sends workbook content to the configured AI provider.</small></span><b>{{ consentGiven ? 'Allowed' : 'Consent required' }}</b></label>
        <details class="analyst-plan"><summary>Analyst plan · inspect → calculate → verify → answer</summary><div><span>1</span>Read workbook columns and data types<span>2</span>Run requested calculations on the active workbook<span>3</span>Return findings with evidence and quality metadata when available</div></details>
        <div v-if="!assistantEnabled" class="assistant-offline">Assistant is paused. Turn the toggle on to ask questions.</div>
        <div class="prompt-row">
          <button v-for="prompt in prompts" :key="prompt" class="prompt-button" :disabled="!assistantEnabled" @click="ask(prompt)">{{ prompt }}</button>
        </div>
        <div class="message-list" aria-live="polite">
          <p v-if="!messages.length" class="helper">Your conversation will appear here.</p>
          <div v-for="(message, index) in messages" :key="index" :class="['message', message.role]">
            <strong>{{ message.role === "user" ? "You" : "Data Analysis Agent" }}</strong>
            <div v-if="message.role === 'assistant' && message.thinking" class="thinking"><span /><span /><span /><span>{{ preferences.liveUpdates ? (status || 'Analyzing your workbook…') : 'Analyzing your workbook…' }}</span><b v-if="preferences.liveUpdates" class="thinking-latency">{{ elapsedMs }} ms</b></div>
            <p v-if="message.text">{{ message.text }}</p>
            <div v-if="message.chart" class="chat-chart"><div class="chat-chart-title"><b>{{ message.chart.title }}</b><span>Generated from workbook data</span></div><img :src="message.chart.url" :alt="message.chart.title" /></div>
            <div v-if="message.changePreview" class="column-change-preview"><div class="column-change-heading"><b>Preview {{ message.changePreview.operation }} column: {{ message.changePreview.column_name }}</b><span>{{ message.applyingChange ? 'Applying and saving a new workbook version' : 'Workbook unchanged until you apply this preview' }}</span></div><p v-if="message.changePreview.formula">Formula: <code>{{ message.changePreview.formula }}</code></p><p v-if="message.changePreview.formula && message.changePreview.validation" class="preview-validation">Computed {{ message.changePreview.validation.populated_rows }} of {{ message.changePreview.validation.rows_evaluated }} rows ({{ message.changePreview.validation.result_coverage_percentage }}% populated).</p><div class="table-scroll"><table class="change-diff"><thead><tr><th>Row</th><th v-if="message.changePreview.operation !== 'add'">Before</th><th v-if="message.changePreview.operation !== 'delete'">After</th></tr></thead><tbody><tr v-for="(row, rowIndex) in message.changePreview.before" :key="rowIndex"><td>{{ rowIndex + 1 }}</td><td v-if="message.changePreview.operation !== 'add'">{{ row[message.changePreview.column_name] ?? "" }}</td><td v-if="message.changePreview.operation !== 'delete'">{{ message.changePreview.after[rowIndex]?.[message.changePreview.column_name] ?? "" }}</td></tr></tbody></table></div><div class="table-scroll"><table><thead><tr><th v-for="column in Object.keys(message.changePreview.after[0] || {})" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="(row, rowIndex) in message.changePreview.after" :key="rowIndex"><td v-for="column in Object.keys(message.changePreview.after[0] || {})" :key="column">{{ row[column] ?? "" }}</td></tr></tbody></table></div><button class="primary-button" type="button" :disabled="message.applyingChange" @click="applyChatColumnChange(message)">{{ message.applyingChange ? 'Applying…' : message.changePreview.operation === 'delete' ? 'Delete column and save new version' : message.changePreview.operation === 'update' ? 'Update column and save new version' : 'Add column and save new version' }}</button><p v-if="message.changeError" class="error-message">{{ message.changeError }}</p></div>
            <div v-if="message.changeApplied" class="change-applied-note" role="status">✓ {{ message.changeAppliedText }}</div>
            <div v-if="message.role === 'assistant' && !message.thinking && message.latencyMs !== null" class="answer-meta"><span class="latency">Latency {{ message.latencyMs }} ms</span><span>Confidence {{ confidencePercent(message.confidence) }}</span><template v-if="preferences.citations"><span v-if="message.citations?.length">{{ message.citations.length }} citation{{ message.citations.length === 1 ? '' : 's' }}</span></template></div>
            <div v-if="preferences.citations && message.citations?.length" class="citations"><span v-for="(citation, citeIndex) in message.citations" :key="citeIndex">{{ citation.source || citation.title || citation }}<small v-if="citation.detail">{{ citation.detail }}</small></span></div>
          </div>
        </div>
        <form class="question-form" @submit.prevent="ask()">
          <input v-model="question" placeholder="Ask anything about your data..." :disabled="sending || !assistantEnabled" />
          <span v-if="sending && preferences.liveUpdates" class="live-latency">{{ elapsedMs }} ms</span>
          <button class="primary-button" type="submit" :disabled="sending || !question.trim() || !assistantEnabled">Send</button>
        </form>
        <div v-if="evaluation && !sending && evaluation.confidence_score !== undefined" class="evaluation-card"><strong>Answer quality</strong><span>Confidence: {{ confidencePercent(evaluation.confidence_score) }}</span><span v-if="preferences.citations && citations.length">{{ citations.length }} citations</span><small v-if="evaluation.evaluation_rationale">{{ evaluation.evaluation_rationale }}</small></div>
      </section>
    </div>
  </section>
</template>
