<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import {
  applyCleaningOperation,
  applyColumnOperation,
  deleteWorkbook,
  generateWorkbookChart,
  getGeneratedCharts,
  getWorkbookDownloadUrl,
  getWorkbookHistory,
  getWorkbookPreview,
  getWorkbookSchema,
  previewCleaningOperation,
  selectWorkbookSheet,
  streamAssistant,
  undoWorkbookChange,
  uploadWorkbook,
} from "../api";
import { preferences } from "../preferences.js";
import {
  getWorkbookThreadId,
  getWorkspaceStorageKey,
} from "../workbookSession.js";
import {
  formatDate,
  formatLatency,
  formatNumber,
  readStoredArray,
} from "../lib/format.js";
import AppIcon from "../components/AppIcon.vue";
import RichText from "../components/RichText.vue";
import AnswerMeta from "../components/AnswerMeta.vue";
import ConfirmDialog from "../components/ConfirmDialog.vue";
import WorkflowRun from "../components/WorkflowRun.vue";

const props = defineProps({
  initialQuestion: { type: String, default: "" },
  active: { type: Boolean, default: true },
});
const emit = defineEmits(["clear-initial", "workbook-change"]);
const threadId = getWorkbookThreadId();
const chatKey = getWorkspaceStorageKey("insightpilot-chat", threadId);
const consentKey = getWorkspaceStorageKey("insightpilot-consent", threadId);
const schema = ref(null);
const preview = ref(null);
const charts = ref([]);
const history = ref({ versions: [], can_undo: false });
const messages = ref(readStoredArray(chatKey, sessionStorage));
const consentGiven = ref(sessionStorage.getItem(consentKey) === "true");
const question = ref("");
const tab = ref("sheet");
const loading = ref(true);
const refreshing = ref(false);
const uploading = ref(false);
const sending = ref(false);
const operationBusy = ref(false);
const deleting = ref(false);
const deleteDialogOpen = ref(false);
const loadError = ref("");
const chartError = ref("");
const notice = ref(null);
const offset = ref(0);
const pageSize = 50;
const selectedCell = ref({ row: 0, column: 0 });
const lastChange = ref(null);
const cleaningPreview = ref(null);
const elapsedMs = ref(0);
const status = ref("");
const fileInput = ref(null);
const chatList = ref(null);
const composer = ref(null);
const consentInput = ref(null);
const grid = ref(null);
const dragActive = ref(false);
let followBottom = true;
let timer;
let controller;
const busy = computed(
  () =>
    uploading.value || sending.value || operationBusy.value || deleting.value,
);
const loaded = computed(() => Boolean(schema.value?.loaded));
const missingCells = computed(() =>
  Object.values(schema.value?.missing_values || {}).reduce(
    (sum, value) => sum + Number(value || 0),
    0,
  ),
);
const selectedValue = computed(() => {
  const column = preview.value?.columns?.[selectedCell.value.column];
  return column
    ? (preview.value?.rows?.[selectedCell.value.row]?.[column] ?? "")
    : "";
});
const cellAddress = computed(
  () =>
    excelColumnLabel(selectedCell.value.column) +
    (offset.value + selectedCell.value.row + 2),
);
const prompts = [
  "Summarize this workbook",
  "Find missing values",
  "Show a useful chart",
];
const tabs = [
  { id: "sheet", label: "Sheet", icon: "table" },
  { id: "charts", label: "Charts", icon: "chart" },
  { id: "quality", label: "Data quality", icon: "shield" },
  { id: "history", label: "History", icon: "history" },
];

function showNotice(text, tone = "success") {
  notice.value = { text, tone };
}
function saveChat() {
  const saved = messages.value
    .filter((message) => !message.thinking)
    .slice(-60)
    .map((message) => ({
      ...message,
      changePreview: undefined,
      applyingChange: false,
      text: message.changePreview
        ? message.text +
          "\n\nThis change was not applied. Ask again to prepare a fresh preview after refreshing."
        : message.text,
    }));
  try {
    sessionStorage.setItem(chatKey, JSON.stringify(saved));
  } catch {
    showNotice(
      "The answer is visible, but this browser could not save the conversation.",
      "warning",
    );
  }
}
function saveAnalysis(answer) {
  const key = getWorkspaceStorageKey("insightpilot-analyses", threadId);
  const entry = {
    id: answer.analysisId,
    question: answer.request,
    answer: answer.text,
    confidence: answer.confidence,
    rationale: answer.rationale,
    citations: answer.citations,
    latencyMs: answer.latencyMs,
    createdAt: answer.createdAt,
    filename: schema.value?.filename,
    chart: answer.chart,
    status:
      answer.error || answer.calculationFailed
        ? answer.chart
          ? "partial"
          : "failed"
        : answer.changePreview
          ? "awaiting_approval"
          : answer.changeCanceled
            ? "canceled"
            : answer.stopped
              ? "stopped"
              : "complete",
    change: answer.changeAppliedText || null,
  };
  try {
    localStorage.setItem(
      key,
      JSON.stringify(
        [
          entry,
          ...readStoredArray(key).filter((item) => item.id !== entry.id),
        ].slice(0, 50),
      ),
    );
  } catch {
    showNotice(
      "The answer is visible, but this browser could not save it to Results.",
      "warning",
    );
  }
}
async function loadSchema() {
  loadError.value = "";
  try {
    const fresh = await getWorkbookSchema(threadId);
    schema.value = fresh;
    emit("workbook-change", fresh);
    if (!fresh.loaded) {
      preview.value = null;
      charts.value = [];
      history.value = { versions: [], can_undo: false };
      return true;
    }
    const maximum = Math.max(
      0,
      Math.floor((fresh.total_rows - 1) / pageSize) * pageSize,
    );
    offset.value = Math.min(offset.value, maximum);
    const responses = await Promise.allSettled([
      getWorkbookPreview(threadId, offset.value, pageSize),
      getGeneratedCharts(threadId),
      getWorkbookHistory(threadId),
    ]);
    if (responses[0].status === "fulfilled") {
      preview.value = responses[0].value;
      selectedCell.value = {
        row: Math.max(
          0,
          Math.min(selectedCell.value.row, preview.value.rows.length - 1),
        ),
        column: Math.max(
          0,
          Math.min(selectedCell.value.column, preview.value.columns.length - 1),
        ),
      };
    } else loadError.value = responses[0].reason.message;
    if (responses[1].status === "fulfilled") {
      charts.value = responses[1].value.charts || [];
      chartError.value = "";
    } else chartError.value = responses[1].reason.message;
    if (responses[2].status === "fulfilled") history.value = responses[2].value;
    else
      showNotice(
        "Workbook loaded. Version history is temporarily unavailable.",
        "warning",
      );
    return responses[0].status === "fulfilled";
  } catch (error) {
    loadError.value = error.message;
    return false;
  } finally {
    loading.value = false;
  }
}
async function refreshWorkbook() {
  if (refreshing.value || busy.value) return;
  refreshing.value = true;
  try {
    if (await loadSchema()) showNotice("Workbook refreshed.");
  } finally {
    refreshing.value = false;
  }
}
async function loadPage(nextOffset) {
  if (refreshing.value || busy.value || !loaded.value) return;
  refreshing.value = true;
  try {
    const result = await getWorkbookPreview(
      threadId,
      Math.max(0, nextOffset),
      pageSize,
    );
    preview.value = result;
    offset.value = result.offset;
    selectedCell.value = { row: 0, column: 0 };
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    refreshing.value = false;
  }
}
function openFilePicker() {
  if (!busy.value) fileInput.value?.click();
}
function selectFile(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (file) ingestWorkbook(file);
}
function dropFile(event) {
  dragActive.value = false;
  const file = event.dataTransfer.files?.[0];
  if (file) ingestWorkbook(file);
}
async function ingestWorkbook(file) {
  if (busy.value) return;
  if (!/\.(xlsx|xlsm)$/i.test(file.name)) {
    showNotice("Choose an Excel workbook (.xlsx or .xlsm).", "error");
    return;
  }
  if (file.size > 20 * 1024 * 1024) {
    showNotice("This workbook exceeds the 20 MB upload limit.", "error");
    return;
  }
  uploading.value = true;
  notice.value = null;
  try {
    await uploadWorkbook(file, threadId);
    for (const prefix of [
      "insightpilot-analyses",
      "datapilot-generated-charts",
      "insightpilot-workflow-runs",
      "insightpilot-hidden-dashboard-charts",
      "insightpilot-dashboard-order",
    ])
      localStorage.removeItem(getWorkspaceStorageKey(prefix, threadId));
    messages.value = [];
    consentGiven.value = false;
    offset.value = 0;
    lastChange.value = null;
    cleaningPreview.value = null;
    tab.value = "sheet";
    sessionStorage.removeItem(chatKey);
    await loadSchema();
    showNotice(
      file.name + " is ready. Allow AI processing to start an analysis.",
    );
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    uploading.value = false;
  }
}
async function removeWorkbook() {
  if (busy.value) return;
  deleting.value = true;
  try {
    await deleteWorkbook(threadId);
    for (const prefix of [
      "insightpilot-analyses",
      "datapilot-generated-charts",
      "insightpilot-workflow-runs",
      "insightpilot-hidden-dashboard-charts",
      "insightpilot-dashboard-order",
    ])
      localStorage.removeItem(getWorkspaceStorageKey(prefix, threadId));
    sessionStorage.removeItem(chatKey);
    schema.value = null;
    preview.value = null;
    charts.value = [];
    messages.value = [];
    consentGiven.value = false;
    lastChange.value = null;
    cleaningPreview.value = null;
    history.value = { versions: [], can_undo: false };
    emit("workbook-change", null);
    showNotice("Workbook and its generated results were deleted.");
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    deleting.value = false;
    deleteDialogOpen.value = false;
  }
}
async function selectSheet(name) {
  if (busy.value || refreshing.value || name === schema.value?.selected_sheet)
    return;
  refreshing.value = true;
  try {
    await selectWorkbookSheet(threadId, name);
    offset.value = 0;
    selectedCell.value = { row: 0, column: 0 };
    cleaningPreview.value = null;
    await loadSchema();
    showNotice("Showing " + name + ".");
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    refreshing.value = false;
  }
}
function excelColumnLabel(index) {
  let label = "";
  let value = index + 1;
  while (value) {
    const remainder = (value - 1) % 26;
    label = String.fromCharCode(65 + remainder) + label;
    value = Math.floor((value - 1) / 26);
  }
  return label;
}
function selectCell(row, column) {
  selectedCell.value = { row, column };
  grid.value?.focus({ preventScroll: true });
}
function moveCell(event) {
  if (
    !preview.value?.rows?.length ||
    ![
      "ArrowUp",
      "ArrowDown",
      "ArrowLeft",
      "ArrowRight",
      "Home",
      "End",
    ].includes(event.key)
  )
    return;
  event.preventDefault();
  let { row, column } = selectedCell.value;
  if (event.key === "ArrowUp") row--;
  if (event.key === "ArrowDown") row++;
  if (event.key === "ArrowLeft") column--;
  if (event.key === "ArrowRight") column++;
  if (event.key === "Home") column = 0;
  if (event.key === "End") column = preview.value.columns.length - 1;
  selectedCell.value = {
    row: Math.max(0, Math.min(row, preview.value.rows.length - 1)),
    column: Math.max(0, Math.min(column, preview.value.columns.length - 1)),
  };
  nextTick(() =>
    document
      .getElementById(
        "workbook-cell-" +
          selectedCell.value.row +
          "-" +
          selectedCell.value.column,
      )
      ?.scrollIntoView({ block: "nearest", inline: "nearest" }),
  );
}
function chartSpecFor(message) {
  const normalize = (value) =>
    String(value)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  const normalized = normalize(message);
  const columns = schema.value?.columns || [];
  const numeric = columns.filter(
    (column) =>
      ["number", "currency", "numeric text"].includes(
        schema.value?.semantic_types?.[column],
      ) ||
      /int|float|decimal|double|numeric/i.test(
        schema.value?.data_types?.[column] || "",
      ),
  );
  const longestMatch = (items) =>
    items
      .filter((column) => normalized.includes(normalize(column)))
      .sort((a, b) => normalize(b).length - normalize(a).length)[0];
  const metric = longestMatch(numeric) || numeric[0] || null;
  const categories = columns.filter(
    (column) => column !== metric && !numeric.includes(column),
  );
  const category =
    longestMatch(categories) ||
    categories.find((column) =>
      ["date", "date text", "category"].includes(
        schema.value?.semantic_types?.[column],
      ),
    ) ||
    null;
  return { metric, category };
}
async function attachChart(answer, signal) {
  const spec = chartSpecFor(answer.request);
  try {
    answer.chart = await generateWorkbookChart(
      threadId,
      spec.metric,
      spec.category,
      signal,
    );
    charts.value = (await getGeneratedCharts(threadId)).charts || [];
    answer.chartError = "";
  } catch (error) {
    if (error.name === "AbortError") throw error;
    answer.chartError = "Chart generation failed: " + error.message;
  }
}
async function applyChange(answer) {
  if (!answer.changePreview || busy.value) return;
  answer.applyingChange = true;
  answer.changeError = "";
  operationBusy.value = true;
  try {
    const result = await applyColumnOperation({
      threadId,
      operationId: answer.changePreview.operation_id,
    });
    answer.changePreview = null;
    const action =
      { add: "Added", update: "Updated", delete: "Deleted" }[
        result.operation
      ] || "Changed";
    answer.changeAppliedText =
      action + " " + result.column_name + ". A new workbook version is saved.";
    lastChange.value = { column: result.column_name, action };
    await loadSchema();
    if (answer.chartAfterChange) await attachChart(answer);
    showNotice(answer.changeAppliedText);
    saveChat();
    saveAnalysis(answer);
  } catch (error) {
    answer.changeError = error.message;
  } finally {
    answer.applyingChange = false;
    operationBusy.value = false;
  }
}
function cancelChange(answer) {
  answer.changePreview = null;
  answer.changeCanceled = true;
  saveChat();
  saveAnalysis(answer);
}
async function previewCleaning(operation) {
  if (busy.value) return;
  operationBusy.value = true;
  try {
    cleaningPreview.value = await previewCleaningOperation(threadId, operation);
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    operationBusy.value = false;
  }
}
async function applyCleaning() {
  if (!cleaningPreview.value || busy.value) return;
  operationBusy.value = true;
  try {
    await applyCleaningOperation(threadId, cleaningPreview.value);
    cleaningPreview.value = null;
    await loadSchema();
    showNotice("Cleaning applied. A new workbook version is saved.");
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    operationBusy.value = false;
  }
}
async function undoChange() {
  if (busy.value) return;
  operationBusy.value = true;
  try {
    await undoWorkbookChange(threadId);
    lastChange.value = null;
    await loadSchema();
    showNotice("The previous workbook version was restored.");
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    operationBusy.value = false;
  }
}
function suggest(text) {
  question.value = text;
  nextTick(() => composer.value?.focus());
}
async function ask() {
  const text = question.value.trim();
  if (!text || busy.value || !loaded.value) return;
  if (!consentGiven.value) {
    consentInput.value?.focus();
    showNotice(
      "Allow AI processing in the agent panel before sending your question.",
      "warning",
    );
    return;
  }
  question.value = "";
  emit("clear-initial");
  followBottom = true;
  messages.value.push({ id: crypto.randomUUID(), role: "user", text });
  const index =
    messages.value.push({
      id: crypto.randomUUID(),
      analysisId: crypto.randomUUID(),
      createdAt: new Date().toISOString(),
      request: text,
      role: "assistant",
      text: "",
      thinking: true,
      steps: [],
      confidence: null,
      citations: [],
      latencyMs: null,
      rationale: "",
      chart: null,
    }) - 1;
  const answer = messages.value[index];
  sending.value = true;
  status.value = "Sending request";
  elapsedMs.value = 0;
  const started = performance.now();
  controller = new AbortController();
  timer = setInterval(() => {
    elapsedMs.value = Math.round(performance.now() - started);
  }, 100);
  const wantsChart = /chart|graph|plot|visual|trend|dashboard/i.test(text);
  try {
    await streamAssistant({
      message: text,
      threadId,
      processingConsent: consentGiven.value,
      signal: controller.signal,
      onEvent(event) {
        if (event.event === "token") answer.text += event.text || "";
        if (event.event === "final_answer")
          answer.text = event.text || answer.text;
        if (event.event === "status" || event.event === "tool_start") {
          status.value =
            event.text || (event.tool ? "Running " + event.tool : "Working");
          if (answer.steps.at(-1) !== status.value)
            answer.steps.push(status.value);
        }
        if (event.event === "error") {
          answer.error = true;
          answer.text =
            event.details ||
            event.message ||
            "The analysis could not complete. Try again.";
        }
        if (event.event === "change_preview")
          answer.changePreview = event.preview;
        if (event.event === "tool_result" && event.success === false)
          answer.calculationFailed = true;
        if (
          event.event === "evaluation" ||
          event.event === "metrics_evaluation"
        ) {
          const metrics =
            event.payload?.evaluation_metrics ||
            event.payload?.metrics ||
            event.payload ||
            event.evaluation_metrics ||
            {};
          const candidates = [event, metrics, event.payload || {}];
          const source =
            candidates.find((item) =>
              Object.prototype.hasOwnProperty.call(item, "confidence_score"),
            ) ||
            candidates.find((item) =>
              Object.prototype.hasOwnProperty.call(item, "confidence"),
            );
          answer.confidence = source
            ? (source.confidence_score ?? source.confidence ?? null)
            : null;
          answer.rationale = metrics.evaluation_rationale || "";
        }
        if (event.event === "citation" || event.event === "citations") {
          const incoming = event.citations || event.payload?.citations || [];
          answer.citations = (
            Array.isArray(incoming) ? incoming : [incoming]
          ).map((item) => (typeof item === "string" ? { source: item } : item));
        }
      },
    });
    if (wantsChart && !answer.error) {
      if (answer.changePreview) answer.chartAfterChange = true;
      else {
        status.value = "Generating workbook chart";
        answer.steps.push(status.value);
        await attachChart(answer, controller.signal);
      }
    }
    if (!answer.text.trim() && !answer.chart && !answer.changePreview) {
      answer.error = true;
      answer.text = "The server returned no answer. Please try again.";
    }
  } catch (error) {
    if (error.name === "AbortError") {
      answer.stopped = true;
      answer.text ||= "Response stopped.";
      answer.confidence = null;
    } else {
      answer.error = true;
      answer.text = error.message;
      answer.confidence = null;
    }
  } finally {
    clearInterval(timer);
    elapsedMs.value = Math.round(performance.now() - started);
    answer.latencyMs = elapsedMs.value;
    answer.thinking = false;
    sending.value = false;
    status.value = "";
    saveChat();
    saveAnalysis(answer);
    await nextTick();
    composer.value?.focus();
  }
}
function handleEnter(event) {
  if (!event.shiftKey && !event.isComposing) {
    event.preventDefault();
    ask();
  }
}
watch(
  () => props.initialQuestion,
  (value) => {
    if (value) {
      suggest(value);
      emit("clear-initial");
    }
  },
  { immediate: true },
);
watch(
  () => props.active,
  (active) => {
    if (active && !loading.value && !busy.value) loadSchema();
  },
);
watch(consentGiven, (value) => {
  sessionStorage.setItem(consentKey, String(value));
});
watch(
  messages,
  () =>
    nextTick(() => {
      if (followBottom && chatList.value)
        chatList.value.scrollTop = chatList.value.scrollHeight;
    }),
  { deep: true, flush: "post" },
);
onMounted(loadSchema);
onBeforeUnmount(() => {
  controller?.abort();
  clearInterval(timer);
});
</script>

<template>
  <section class="data-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">Your analysis workspace</p>
        <h1>Data workspace</h1>
        <p>Inspect your workbook. Ask a question. See what changes.</p>
      </div>
      <div class="page-actions">
        <button
          v-if="loaded"
          class="icon-button bordered"
          :disabled="busy || refreshing"
          aria-label="Refresh workbook"
          title="Refresh workbook"
          @click="refreshWorkbook"
        >
          <AppIcon name="refresh" :class="{ spinning: refreshing }" />
        </button>
        <a
          v-if="loaded"
          class="button secondary"
          :href="getWorkbookDownloadUrl(threadId)"
          download
          ><AppIcon name="download" :size="15" /><span>Save workbook</span></a
        >
        <button class="button primary" :disabled="busy" @click="openFilePicker">
          <span v-if="uploading" class="spinner" /><AppIcon
            v-else
            name="upload"
            :size="15"
          />{{
            uploading
              ? "Uploading…"
              : loaded
                ? "Replace workbook"
                : "Upload workbook"
          }}
        </button>
      </div>
    </header>
    <input
      ref="fileInput"
      class="sr-only"
      tabindex="-1"
      type="file"
      accept=".xlsx,.xlsm"
      aria-label="Choose an Excel workbook"
      :disabled="busy"
      @change="selectFile"
    />
    <div
      v-if="notice"
      :class="['notice', notice.tone]"
      :role="notice.tone === 'error' ? 'alert' : 'status'"
    >
      <AppIcon
        :name="notice.tone === 'error' ? 'alert' : 'check'"
        :size="16"
      /><span>{{ notice.text }}</span
      ><button
        class="icon-button"
        aria-label="Dismiss notification"
        @click="notice = null"
      >
        <AppIcon name="close" :size="14" />
      </button>
    </div>
    <div v-if="loadError" class="notice error" role="alert">
      <AppIcon name="alert" :size="16" /><span
        >Could not refresh the workbook: {{ loadError }}</span
      ><button
        class="text-button"
        :disabled="refreshing"
        @click="refreshWorkbook"
      >
        Retry
      </button>
    </div>

    <div class="workbench">
      <section class="sheet-panel surface" :aria-busy="uploading || refreshing">
        <header class="sheet-header">
          <span class="file-icon"><AppIcon name="table" :size="21" /></span>
          <div class="file-summary">
            <h2>{{ loaded ? schema.filename : "No workbook selected" }}</h2>
            <p v-if="loaded">
              {{ formatNumber(schema.total_rows) }} rows<span>·</span
              >{{ schema.columns.length }} columns<span>·</span>Saved in this
              workspace
            </p>
            <p v-else>Excel workbooks · .xlsx and .xlsm</p>
          </div>
          <button
            v-if="loaded"
            class="icon-button destructive"
            title="Delete workbook"
            aria-label="Delete workbook"
            :disabled="busy"
            @click="deleteDialogOpen = true"
          >
            <AppIcon name="trash" :size="17" />
          </button>
        </header>
        <div v-if="loading && !schema" class="panel-loading">
          <span class="spinner" />Opening your workspace…
        </div>
        <div
          v-else-if="!loaded"
          class="upload-empty"
          :class="{ dragging: dragActive }"
          @dragover.prevent="dragActive = true"
          @dragleave.prevent="dragActive = false"
          @drop.prevent="dropFile"
        >
          <div class="empty-sheet-art" aria-hidden="true">
            <AppIcon name="table" :size="36" /><span class="art-plus">+</span>
          </div>
          <h2>Bring your data into focus</h2>
          <p>
            Drop an Excel workbook here to explore its sheets, find insights,
            and prepare changes with the agent.
          </p>
          <button
            class="button primary"
            :disabled="uploading"
            @click="openFilePicker"
          >
            <AppIcon name="upload" :size="16" />{{
              uploading ? "Uploading…" : "Choose a workbook"
            }}</button
          ><small>.xlsx or .xlsm · up to 20 MB</small>
          <div class="start-steps">
            <span><b>01</b>Upload your workbook</span
            ><span><b>02</b>Ask about your data</span
            ><span><b>03</b>Review the results</span>
          </div>
        </div>
        <template v-else>
          <nav class="panel-tabs" aria-label="Workbook views">
            <button
              v-for="item in tabs"
              :key="item.id"
              :class="{ active: tab === item.id }"
              :aria-current="tab === item.id ? 'page' : undefined"
              @click="tab = item.id"
            >
              <AppIcon :name="item.icon" :size="15" />{{ item.label
              }}<span
                v-if="item.id === 'charts' && charts.length"
                class="count"
                >{{ charts.length }}</span
              >
            </button>
          </nav>
          <template v-if="tab === 'sheet'">
            <div class="formula-bar">
              <span class="cell-address">{{ cellAddress }}</span
              ><span class="formula-symbol">fx</span
              ><input
                :value="selectedValue"
                readonly
                aria-label="Selected cell value"
                placeholder="Select a cell to inspect its value"
              /><span class="preview-badge">Workbook preview</span>
            </div>
            <div v-if="lastChange" class="sheet-change" role="status">
              <AppIcon name="check" :size="14" />{{ lastChange.action }}
              {{ lastChange.column }}<span>Saved version is visible below</span
              ><button
                class="icon-button"
                aria-label="Dismiss change indicator"
                @click="lastChange = null"
              >
                <AppIcon name="close" :size="13" />
              </button>
            </div>
            <div v-if="preview" class="spreadsheet-scroll">
              <table
                ref="grid"
                class="spreadsheet"
                :class="{ compact: preferences.compactTables }"
                role="grid"
                tabindex="0"
                aria-label="Workbook preview. Use arrow keys to inspect cells."
                :aria-rowcount="preview.total_rows + 1"
                :aria-colcount="preview.columns.length + 1"
                :aria-activedescendant="
                  preview.rows.length
                    ? 'workbook-cell-' +
                      selectedCell.row +
                      '-' +
                      selectedCell.column
                    : undefined
                "
                @keydown="moveCell"
              >
                <thead>
                  <tr class="sheet-letters" aria-hidden="true">
                    <th class="row-index corner-cell" />
                    <th
                      v-for="(column, index) in preview.columns"
                      :key="column"
                      :class="{
                        'changed-column': lastChange?.column === column,
                      }"
                    >
                      {{ excelColumnLabel(index) }}
                    </th>
                  </tr>
                  <tr class="sheet-column-names">
                    <th class="row-index">1</th>
                    <th
                      v-for="column in preview.columns"
                      :key="column"
                      scope="col"
                      :title="column"
                      :class="{
                        'changed-column': lastChange?.column === column,
                      }"
                    >
                      {{ column.replace(/\s+/g, " ") }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(row, rowIndex) in preview.rows"
                    :key="rowIndex"
                    :aria-rowindex="preview.offset + rowIndex + 2"
                  >
                    <th class="row-index" scope="row">
                      {{ preview.offset + rowIndex + 2 }}
                    </th>
                    <td
                      v-for="(column, columnIndex) in preview.columns"
                      :id="'workbook-cell-' + rowIndex + '-' + columnIndex"
                      :key="column"
                      :title="String(row[column] ?? '')"
                      :class="{
                        selected:
                          selectedCell.row === rowIndex &&
                          selectedCell.column === columnIndex,
                        numeric: typeof row[column] === 'number',
                        'changed-column': lastChange?.column === column,
                        empty: row[column] === null,
                      }"
                      @click="selectCell(rowIndex, columnIndex)"
                    >
                      {{ row[column] ?? "" }}
                    </td>
                  </tr>
                </tbody>
              </table>
              <div v-if="!preview.rows.length" class="sheet-no-rows">
                This worksheet has no data rows.
              </div>
            </div>
            <div v-else class="panel-loading">
              <span class="spinner" />Loading sheet preview…
            </div>
            <footer class="sheet-footer">
              <div class="worksheet-tabs" aria-label="Worksheets">
                <button
                  v-for="sheet in schema.sheet_names"
                  :key="sheet"
                  :class="{ active: sheet === schema.selected_sheet }"
                  :disabled="busy || refreshing"
                  @click="selectSheet(sheet)"
                >
                  <AppIcon name="table" :size="13" />{{ sheet
                  }}<small v-if="schema.hidden_sheets?.includes(sheet)"
                    >hidden</small
                  >
                </button>
              </div>
              <div class="page-controls">
                <span
                  >{{ preview?.rows?.length ? offset + 1 : 0 }}–{{
                    offset + (preview?.rows?.length || 0)
                  }}
                  of {{ formatNumber(schema.total_rows) }}</span
                ><button
                  class="icon-button"
                  :disabled="busy || refreshing || offset === 0"
                  aria-label="Previous rows"
                  @click="loadPage(offset - pageSize)"
                >
                  <AppIcon
                    name="chevron"
                    :size="15"
                    class="rotate-180"
                  /></button
                ><button
                  class="icon-button"
                  :disabled="
                    busy || refreshing || offset + pageSize >= schema.total_rows
                  "
                  aria-label="Next rows"
                  @click="loadPage(offset + pageSize)"
                >
                  <AppIcon name="chevron" :size="15" />
                </button>
              </div>
            </footer>
          </template>
          <div v-else-if="tab === 'charts'" class="panel-body scroll-body">
            <div class="section-heading">
              <div>
                <h3>Workbook charts</h3>
                <p>Generated from your requests and workbook profiles.</p>
              </div>
              <span class="subtle-label">{{ charts.length }} saved</span>
            </div>
            <p v-if="chartError" class="notice error">{{ chartError }}</p>
            <div v-if="!charts.length" class="panel-empty">
              <AppIcon name="chart" :size="30" />
              <h3>A visual answer starts with a question</h3>
              <p>
                Ask the agent for a chart. It will appear in the conversation
                and here.
              </p>
              <button
                class="button secondary"
                @click="suggest('Show a useful chart from this workbook')"
              >
                Ask for a chart<AppIcon name="arrow" :size="15" />
              </button>
            </div>
            <article
              v-for="chart in charts"
              :key="chart.url"
              class="chart-card"
            >
              <header>
                <h3>{{ chart.title }}</h3>
                <a
                  :href="chart.url"
                  class="icon-button"
                  download
                  title="Download chart"
                  aria-label="Download chart"
                  ><AppIcon name="download" :size="16"
                /></a>
              </header>
              <img :src="chart.url" :alt="chart.title" loading="lazy" />
              <p>
                {{ chart.column
                }}<template v-if="chart.category_column">
                  by {{ chart.category_column }}</template
                >
              </p>
            </article>
          </div>
          <div
            v-else-if="tab === 'quality'"
            class="panel-body scroll-body quality-body"
          >
            <div class="quality-summary">
              <div>
                <span>Rows</span
                ><strong>{{ formatNumber(schema.total_rows) }}</strong>
              </div>
              <div>
                <span>Columns</span><strong>{{ schema.columns.length }}</strong>
              </div>
              <div :class="{ warning: missingCells }">
                <span>Missing cells</span
                ><strong>{{ formatNumber(missingCells) }}</strong>
              </div>
            </div>
            <div class="section-heading">
              <div>
                <h3>Column health</h3>
                <p>Missing-cell counts cover the active worksheet.</p>
              </div>
            </div>
            <div class="simple-table-wrap">
              <table class="simple-table">
                <thead>
                  <tr>
                    <th>Column</th>
                    <th>Type</th>
                    <th>Missing cells</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="column in schema.columns" :key="column">
                    <td>{{ column }}</td>
                    <td>
                      <span class="type-tag">{{
                        schema.semantic_types?.[column] ||
                        schema.data_types?.[column]
                      }}</span>
                    </td>
                    <td
                      :class="{
                        'text-warning': schema.missing_values?.[column],
                      }"
                    >
                      {{ formatNumber(schema.missing_values?.[column] || 0) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <section class="cleaning-section">
              <div class="section-heading">
                <div>
                  <h3>Clean with a preview</h3>
                  <p>Review the impact before saving a new workbook version.</p>
                </div>
              </div>
              <div class="action-row">
                <button
                  class="button secondary"
                  :disabled="busy"
                  @click="previewCleaning('remove_duplicates')"
                >
                  Remove duplicates</button
                ><button
                  class="button secondary"
                  :disabled="busy"
                  @click="previewCleaning('drop_missing_rows')"
                >
                  Remove missing rows
                </button>
              </div>
              <div v-if="cleaningPreview" class="approval-card">
                <b>{{ cleaningPreview.label }}</b>
                <p>
                  {{ formatNumber(cleaningPreview.rows_removed) }} rows will be
                  removed. {{ formatNumber(cleaningPreview.rows_after) }} rows
                  remain.
                </p>
                <div class="action-row">
                  <button
                    class="button primary"
                    :disabled="busy"
                    @click="applyCleaning"
                  >
                    Approve & apply</button
                  ><button
                    class="button secondary"
                    :disabled="busy"
                    @click="cleaningPreview = null"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </section>
            <WorkflowRun :thread-id="threadId" @complete="loadSchema" />
          </div>
          <div v-else class="panel-body scroll-body">
            <div class="section-heading">
              <div>
                <h3>Workbook history</h3>
                <p>
                  Approved edits and cleaning actions create saved versions.
                </p>
              </div>
              <button
                v-if="history.can_undo"
                class="button secondary"
                :disabled="busy"
                @click="undoChange"
              >
                <AppIcon name="undo" :size="15" />Restore previous
              </button>
            </div>
            <div v-if="!history.versions?.length" class="panel-empty">
              <AppIcon name="history" :size="30" />
              <h3>No changes yet</h3>
              <p>
                Ask the agent to prepare a column change. Approve its preview to
                create a version.
              </p>
            </div>
            <ol v-else class="version-list">
              <li
                v-for="(version, index) in history.versions"
                :key="version.created_at + '-' + index"
              >
                <span class="version-dot" />
                <div>
                  <b>{{ version.operation || "Workbook change" }}</b
                  ><small>{{ version.filename }}</small
                  ><time>{{ formatDate(version.created_at) }}</time>
                </div>
                <span
                  class="status-tag"
                  :class="{ neutral: !version.restorable }"
                  >{{ version.restorable ? "Restorable" : "Unavailable" }}</span
                >
              </li>
            </ol>
          </div>
        </template>
      </section>

      <section class="agent-panel surface" aria-label="Data Analysis Agent">
        <header class="agent-header">
          <span class="icon-tile small"
            ><AppIcon name="sparkle" :size="18"
          /></span>
          <div>
            <h2>Data Analysis Agent</h2>
            <p>
              {{
                sending
                  ? "Working with your workbook"
                  : loaded
                    ? "Ready for your next question"
                    : "Connect a workbook to begin"
              }}
            </p>
          </div>
          <span class="agent-dot" :class="{ working: sending }" />
        </header>
        <label v-if="loaded && !consentGiven" class="processing-consent"
          ><input
            ref="consentInput"
            v-model="consentGiven"
            type="checkbox"
          /><AppIcon name="shield" :size="18" /><span
            ><b>Allow AI processing</b
            ><small
              >Your question and relevant workbook content may be sent to the
              configured AI provider.</small
            ></span
          ></label
        >
        <div v-else-if="loaded" class="consent-status">
          <AppIcon name="shield" :size="13" /><span>AI processing allowed</span
          ><button
            class="text-button"
            :disabled="sending"
            @click="consentGiven = false"
          >
            Change
          </button>
        </div>
        <div
          ref="chatList"
          class="conversation"
          role="log"
          aria-label="Workbook conversation"
          aria-live="polite"
          @scroll="
            followBottom =
              $event.target.scrollHeight -
                $event.target.scrollTop -
                $event.target.clientHeight <
              100
          "
        >
          <div v-if="!messages.length" class="agent-welcome">
            <span class="welcome-symbol"
              ><AppIcon name="sparkle" :size="25"
            /></span>
            <h3>Your data, explained.</h3>
            <p>
              Ask for insights or charts. When you need a workbook change, I’ll
              prepare a preview for your approval.
            </p>
            <div class="starter-prompts">
              <button
                v-for="prompt in prompts"
                :key="prompt"
                class="suggestion"
                :disabled="!loaded"
                @click="suggest(prompt)"
              >
                {{ prompt }}<AppIcon name="arrow" :size="14" />
              </button>
            </div>
            <span class="welcome-footnote"
              ><AppIcon name="shield" :size="12" />Edits wait for your
              approval</span
            >
          </div>
          <article
            v-for="message in messages"
            :key="message.id"
            class="conversation-message"
            :class="[message.role, { failed: message.error }]"
          >
            <div class="message-author">
              <span>{{
                message.role === "user" ? "You" : "Data Analysis Agent"
              }}</span
              ><span v-if="message.stopped" class="subtle-label">Stopped</span>
            </div>
            <RichText v-if="message.text" :text="message.text" />
            <div v-if="message.thinking" class="thinking-line" role="status">
              <span class="thinking-dots"><i /><i /><i /></span
              ><span>{{
                preferences.liveUpdates ? status : "Analyzing workbook"
              }}</span
              ><b class="latency">{{ formatLatency(elapsedMs) }}</b>
            </div>
            <details
              v-if="preferences.liveUpdates && message.steps?.length"
              class="execution-details"
            >
              <summary>
                {{ message.thinking ? "Live activity" : "View activity"
                }}<AppIcon name="down" :size="12" />
              </summary>
              <ol>
                <li v-for="(step, stepIndex) in message.steps" :key="stepIndex">
                  {{ step }}
                </li>
              </ol>
            </details>
            <figure v-if="message.chart" class="answer-chart">
              <p v-if="message.calculationFailed" class="notice warning">
                The chart was generated directly from the workbook. The written
                calculation did not complete, so its totals are unverified.
              </p>
              <figcaption>
                <b>{{ message.chart.title }}</b
                ><a
                  :href="message.chart.url"
                  class="icon-button"
                  download
                  aria-label="Download generated chart"
                  ><AppIcon name="download" :size="15"
                /></a>
              </figcaption>
              <img :src="message.chart.url" :alt="message.chart.title" /><small
                >Generated from the active workbook · saved in Results</small
              >
            </figure>
            <p v-if="message.chartError" class="notice error">
              {{ message.chartError }}
            </p>
            <section v-if="message.changePreview" class="approval-card">
              <span class="status-tag warning">Approval needed</span>
              <h3>
                {{
                  message.changePreview.operation === "delete"
                    ? "Delete"
                    : message.changePreview.operation === "update"
                      ? "Update"
                      : "Add"
                }}
                {{ message.changePreview.column_name }}
              </h3>
              <p>
                The workbook will be updated only after you approve this change.
              </p>
              <code v-if="message.changePreview.formula" class="formula-code">{{
                message.changePreview.formula
              }}</code>
              <div class="simple-table-wrap">
                <table class="simple-table change-table">
                  <thead>
                    <tr>
                      <th>Row</th>
                      <th v-if="message.changePreview.operation !== 'add'">
                        Before
                      </th>
                      <th v-if="message.changePreview.operation !== 'delete'">
                        After
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="(row, rowIndex) in message.changePreview.before"
                      :key="rowIndex"
                    >
                      <td>{{ rowIndex + 1 }}</td>
                      <td v-if="message.changePreview.operation !== 'add'">
                        {{ row[message.changePreview.column_name] ?? "—" }}
                      </td>
                      <td
                        v-if="message.changePreview.operation !== 'delete'"
                        class="after-value"
                      >
                        {{
                          message.changePreview.after[rowIndex]?.[
                            message.changePreview.column_name
                          ] ?? "—"
                        }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <small v-if="message.changePreview.validation"
                >{{ message.changePreview.validation.populated_rows }} of
                {{ message.changePreview.validation.rows_evaluated }} rows
                populated.</small
              >
              <p v-if="message.chartAfterChange" class="helper">
                The requested chart will be generated after this change is
                approved.
              </p>
              <div class="action-row">
                <button
                  class="button primary"
                  :disabled="busy"
                  @click="applyChange(message)"
                >
                  <span v-if="message.applyingChange" class="spinner" />{{
                    message.applyingChange
                      ? "Applying & saving…"
                      : "Approve & apply"
                  }}</button
                ><button
                  class="button secondary"
                  :disabled="busy"
                  @click="cancelChange(message)"
                >
                  Cancel
                </button>
              </div>
              <p v-if="message.changeError" class="text-error" role="alert">
                {{ message.changeError }}
              </p>
            </section>
            <p
              v-if="message.changeAppliedText"
              class="applied-note"
              role="status"
            >
              <AppIcon name="check" :size="15" />{{ message.changeAppliedText }}
            </p>
            <p v-if="message.changeCanceled" class="helper">
              Change canceled. The workbook is unchanged.
            </p>
            <AnswerMeta
              v-if="message.role === 'assistant' && !message.thinking"
              :confidence="message.confidence"
              :latency-ms="message.latencyMs"
              :citations="message.citations || []"
              :rationale="message.rationale || ''"
            />
          </article>
        </div>
        <form class="agent-composer" @submit.prevent="ask">
          <label class="sr-only" for="data-question"
            >Ask the Data Analysis Agent</label
          >
          <div class="composer-input">
            <textarea
              id="data-question"
              ref="composer"
              v-model="question"
              rows="2"
              maxlength="8000"
              :placeholder="
                loaded
                  ? 'Ask about your workbook…'
                  : 'Upload a workbook to ask a question'
              "
              :disabled="sending || !loaded"
              @keydown.enter="handleEnter"
            /><button
              v-if="sending"
              type="button"
              class="send-button stop"
              aria-label="Stop analysis"
              @click="controller?.abort()"
            >
              <AppIcon name="stop" :size="17" /></button
            ><button
              v-else
              class="send-button"
              :disabled="!question.trim() || !loaded || busy"
              aria-label="Send analysis question"
            >
              <AppIcon name="send" :size="19" />
            </button>
          </div>
          <span class="composer-hint"
            >Enter to send<span>Shift + Enter for a new line</span></span
          >
        </form>
      </section>
    </div>
    <ConfirmDialog
      :open="deleteDialogOpen"
      :busy="deleting"
      title="Delete this workbook?"
      message="This removes the saved workbook, its versions, charts, and analysis history from this workspace."
      confirm-label="Delete workbook"
      @cancel="deleteDialogOpen = false"
      @confirm="removeWorkbook"
    />
  </section>
</template>
