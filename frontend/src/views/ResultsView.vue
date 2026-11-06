<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { getGeneratedCharts, getWorkbookSchema } from "../api";
import {
  getWorkbookThreadId,
  getWorkspaceStorageKey,
} from "../workbookSession.js";
import {
  downloadJson,
  formatDate,
  formatNumber,
  readStoredArray,
} from "../lib/format.js";
import AppIcon from "../components/AppIcon.vue";
import RichText from "../components/RichText.vue";
import AnswerMeta from "../components/AnswerMeta.vue";
const props = defineProps({ active: Boolean });
const emit = defineEmits(["navigate"]);
const threadId = getWorkbookThreadId();
const loading = ref(false);
const error = ref("");
const schema = ref(null);
const analyses = ref([]);
const charts = ref([]);
const runs = ref([]);
const tab = ref("answers");
const query = ref("");
const filteredAnswers = computed(() =>
  analyses.value.filter((item) =>
    (item.question + " " + item.answer)
      .toLowerCase()
      .includes(query.value.toLowerCase()),
  ),
);
const filteredCharts = computed(() =>
  charts.value.filter((item) =>
    (item.title + " " + item.column)
      .toLowerCase()
      .includes(query.value.toLowerCase()),
  ),
);
const statusLabel = (status) =>
  ({
    failed: "Failed",
    partial: "Chart available · analysis incomplete",
    awaiting_approval: "Preview prepared",
    canceled: "Canceled",
    stopped: "Stopped",
  })[status] || "Completed";
async function load() {
  loading.value = true;
  error.value = "";
  analyses.value = readStoredArray(
    getWorkspaceStorageKey("insightpilot-analyses", threadId),
  );
  runs.value = readStoredArray(
    getWorkspaceStorageKey("insightpilot-workflow-runs", threadId),
  );
  try {
    const [workbook, artifacts] = await Promise.all([
      getWorkbookSchema(threadId),
      getGeneratedCharts(threadId),
    ]);
    schema.value = workbook;
    charts.value = artifacts.charts || [];
  } catch (caught) {
    error.value = caught.message;
  } finally {
    loading.value = false;
  }
}
function exportResults() {
  downloadJson(
    {
      workbook: schema.value?.filename,
      exportedAt: new Date().toISOString(),
      answers: analyses.value,
      charts: charts.value,
      profiles: runs.value,
    },
    "insightpilot-results.json",
  );
}
watch(
  () => props.active,
  (active) => {
    if (active) load();
  },
);
onMounted(() => {
  if (props.active) load();
});
</script>

<template>
  <section class="results-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">From questions to findings</p>
        <h1>Results</h1>
        <p>Answers, charts, and profile runs from this workbook.</p>
      </div>
      <div class="page-actions">
        <button
          class="icon-button bordered"
          :disabled="loading"
          title="Refresh results"
          aria-label="Refresh results"
          @click="load"
        >
          <AppIcon name="refresh" :class="{ spinning: loading }" /></button
        ><button
          class="button secondary"
          :disabled="!analyses.length && !charts.length && !runs.length"
          @click="exportResults"
        >
          <AppIcon name="download" :size="15" />Export results
        </button>
      </div>
    </header>
    <div v-if="error" class="notice error" role="alert">
      <AppIcon name="alert" :size="16" /><span>{{ error }}</span
      ><button class="text-button" @click="load">Retry</button>
    </div>
    <div class="results-context">
      <span class="file-icon"><AppIcon name="table" :size="19" /></span>
      <div>
        <b>{{
          schema?.loaded
            ? schema.filename
            : loading
              ? "Loading workbook…"
              : "No active workbook"
        }}</b
        ><small>{{
          schema?.loaded
            ? formatNumber(schema.total_rows) +
              " rows · " +
              schema.columns.length +
              " columns"
            : loading
              ? "Retrieving the saved workspace."
              : "Upload a workbook in the workspace to create results."
        }}</small>
      </div>
      <span class="subtle-label">Current workspace</span>
    </div>
    <div class="results-toolbar">
      <nav class="segmented-tabs" aria-label="Result types">
        <button :class="{ active: tab === 'answers' }" @click="tab = 'answers'">
          Answers<span>{{ analyses.length }}</span></button
        ><button :class="{ active: tab === 'charts' }" @click="tab = 'charts'">
          Charts<span>{{ charts.length }}</span></button
        ><button :class="{ active: tab === 'runs' }" @click="tab = 'runs'">
          Profile runs<span>{{ runs.length }}</span>
        </button>
      </nav>
      <label v-if="tab !== 'runs'" class="search-field"
        ><AppIcon name="search" :size="15" /><input
          v-model="query"
          aria-label="Filter saved results"
          placeholder="Find a result…"
      /></label>
    </div>
    <div
      v-if="loading && !analyses.length && !charts.length"
      class="panel-loading surface"
    >
      <span class="spinner" />Loading your results…
    </div>
    <template v-else-if="tab === 'answers'">
      <div v-if="!filteredAnswers.length" class="large-empty surface">
        <span class="icon-tile"><AppIcon name="message" :size="25" /></span>
        <h2>
          {{ query ? "No matching answers" : "Your findings will live here" }}
        </h2>
        <p>
          {{
            query
              ? "Try a different search."
              : "Ask a question in the workspace. Answers arrive here with their evidence and timing."
          }}
        </p>
        <button
          v-if="!query"
          class="button primary"
          @click="emit('navigate', { id: 'workspace' })"
        >
          Open workspace<AppIcon name="arrow" :size="15" />
        </button>
      </div>
      <div v-else class="answer-library">
        <details
          v-for="(analysis, index) in filteredAnswers"
          :key="analysis.id"
          class="saved-answer surface"
          :open="index === 0"
        >
          <summary>
            <span class="result-icon"
              ><AppIcon name="message" :size="17"
            /></span>
            <div>
              <h2>{{ analysis.question }}</h2>
              <time>{{ formatDate(analysis.createdAt) }}</time>
            </div>
            <span
              class="status-tag"
              :class="{
                warning: ['awaiting_approval', 'partial'].includes(
                  analysis.status,
                ),
                error: analysis.status === 'failed',
                neutral: ['canceled', 'stopped'].includes(analysis.status),
              }"
              >{{ statusLabel(analysis.status) }}</span
            ><AppIcon name="down" :size="16" />
          </summary>
          <div class="saved-answer-body">
            <RichText
              :text="analysis.answer || 'No answer text was returned.'"
            />
            <p v-if="analysis.change" class="applied-note">
              <AppIcon name="check" :size="15" />{{ analysis.change }}
            </p>
            <figure v-if="analysis.chart" class="answer-chart">
              <figcaption>{{ analysis.chart.title }}</figcaption>
              <img
                :src="analysis.chart.url"
                :alt="analysis.chart.title"
                loading="lazy"
              />
            </figure>
            <AnswerMeta
              :confidence="analysis.confidence"
              :latency-ms="analysis.latencyMs"
              :citations="analysis.citations || []"
              :rationale="analysis.rationale || ''"
            /><button
              class="text-button continue-analysis"
              @click="
                emit('navigate', { id: 'workspace', query: analysis.question })
              "
            >
              Continue in workspace<AppIcon name="arrow" :size="14" />
            </button>
          </div>
        </details>
      </div>
    </template>
    <template v-else-if="tab === 'charts'">
      <div v-if="!filteredCharts.length" class="large-empty surface">
        <span class="icon-tile"><AppIcon name="chart" :size="25" /></span>
        <h2>
          {{
            query ? "No matching charts" : "Charts from your data, saved here"
          }}
        </h2>
        <p>
          {{
            query
              ? "Try a different search."
              : "Ask the agent for a chart or run a workbook profile. Only generated workbook artifacts appear here."
          }}
        </p>
        <button
          v-if="!query"
          class="button primary"
          @click="
            emit('navigate', {
              id: 'workspace',
              query: 'Show a useful chart from this workbook',
            })
          "
        >
          Ask for a chart<AppIcon name="arrow" :size="15" />
        </button>
      </div>
      <div v-else class="results-chart-grid">
        <article
          v-for="chart in filteredCharts"
          :key="chart.url"
          class="chart-card surface"
        >
          <header>
            <div>
              <h2>{{ chart.title }}</h2>
              <p>
                {{ chart.column
                }}<template v-if="chart.category_column">
                  by {{ chart.category_column }}</template
                >
              </p>
            </div>
            <a
              class="icon-button"
              :href="chart.url"
              download
              title="Download chart"
              aria-label="Download chart"
              ><AppIcon name="download" :size="17"
            /></a>
          </header>
          <img :src="chart.url" :alt="chart.title" loading="lazy" />
          <footer>
            <span class="status-tag neutral">Workbook generated</span
            ><a
              :href="chart.url"
              target="_blank"
              rel="noopener noreferrer"
              class="text-button"
              >Open chart<AppIcon name="external" :size="13"
            /></a>
          </footer>
        </article>
      </div>
    </template>
    <template v-else>
      <div v-if="!runs.length" class="large-empty surface">
        <span class="icon-tile"><AppIcon name="shield" :size="25" /></span>
        <h2>See the health of your workbook</h2>
        <p>
          Run a quick profile from the Data quality tab in the workspace. Its
          output will be saved here.
        </p>
        <button
          class="button primary"
          @click="emit('navigate', { id: 'workspace' })"
        >
          Open workspace<AppIcon name="arrow" :size="15" />
        </button>
      </div>
      <article
        v-for="run in runs"
        :key="run.id"
        class="profile-history-card surface"
      >
        <header>
          <span class="file-icon"><AppIcon name="shield" :size="20" /></span>
          <div>
            <h2>{{ run.filename }}</h2>
            <time>{{ formatDate(run.createdAt) }}</time>
          </div>
          <span class="status-tag">Completed</span>
        </header>
        <p>{{ run.summary }}</p>
        <div class="run-metrics">
          <span
            ><b>{{ formatNumber(run.rows) }}</b
            >Rows</span
          ><span
            ><b>{{ run.fields }}</b
            >Columns</span
          ><span
            ><b>{{ run.charts }}</b
            >Charts</span
          ><span
            ><b>{{ formatNumber(run.missing) }}</b
            >Missing cells</span
          >
        </div>
      </article>
    </template>
  </section>
</template>
