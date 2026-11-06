<script setup>
import { computed, onBeforeUnmount, ref } from "vue";
import { processDocuments } from "../api";
import { extractionFor, fieldsFor } from "../lib/documents.js";
import {
  formatConfidence,
  formatDate,
  formatLatency,
  readStoredArray,
} from "../lib/format.js";
import AppIcon from "../components/AppIcon.vue";
const files = ref([]);
const consent = ref(false);
const processing = ref(false);
const error = ref("");
const status = ref("");
const progress = ref([]);
const elapsed = ref(0);
const savedJobs = ref(readStoredArray("insightpilot-document-jobs"));
const result = ref(savedJobs.value[0] || null);
const input = ref(null);
const dragActive = ref(false);
const flags = computed(() => result.value?.review_report?.flagged_fields || []);
const outputNames = {
  documents_json: "Extracted data",
  review_report_json: "Review report",
  excel: "Excel workbook",
  evaluation_json: "Quality report",
};
let timer;
let controller;
function addFiles(selected) {
  error.value = "";
  const next = Array.from(selected);
  if (next.length > 20) {
    error.value = "Choose up to 20 files per job.";
    return;
  }
  const unsupported = next.find(
    (file) => !/\.(pdf|jpe?g|png|webp)$/i.test(file.name),
  );
  if (unsupported) {
    error.value = unsupported.name + ": choose PDF, JPEG, PNG, or WebP.";
    return;
  }
  const tooLarge = next.find((file) => file.size > 20 * 1024 * 1024);
  if (tooLarge) {
    error.value = tooLarge.name + " exceeds the 20 MB per-file limit.";
    return;
  }
  files.value = next;
  consent.value = false;
}
function selectFiles(event) {
  addFiles(event.target.files);
  event.target.value = "";
}
function formatBytes(value) {
  return value < 1024 * 1024
    ? Math.max(1, Math.round(value / 1024)) + " KB"
    : (value / (1024 * 1024)).toFixed(1) + " MB";
}
function label(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
function fieldValue(value) {
  return value === null || value === undefined || value === ""
    ? "Not extracted"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
}
async function process() {
  if (processing.value || !files.value.length || !consent.value) return;
  processing.value = true;
  error.value = "";
  status.value = "Uploading documents";
  progress.value = [];
  result.value = null;
  elapsed.value = 0;
  const started = performance.now();
  controller = new AbortController();
  timer = setInterval(() => {
    elapsed.value = Math.round(performance.now() - started);
  }, 100);
  try {
    await processDocuments({
      files: files.value,
      signal: controller.signal,
      onEvent(event) {
        if (event.type === "progress") {
          status.value = event.message || label(event.stage);
          if (progress.value.at(-1) !== status.value)
            progress.value.push(status.value);
        }
        if (event.type === "complete")
          result.value = {
            ...event.result,
            createdAt: new Date().toISOString(),
          };
        if (event.type === "error")
          throw new Error(
            event.message || "Document processing could not complete.",
          );
      },
    });
    if (!result.value)
      throw new Error(
        "The connection ended without a document result. Please try again.",
      );
    savedJobs.value = [
      result.value,
      ...savedJobs.value.filter((job) => job.job_id !== result.value.job_id),
    ].slice(0, 30);
    try {
      localStorage.setItem(
        "insightpilot-document-jobs",
        JSON.stringify(savedJobs.value),
      );
    } catch {
      error.value =
        "Processing completed. This browser could not save the job to recent history.";
    }
    files.value = [];
    consent.value = false;
    status.value = "Review ready";
  } catch (caught) {
    error.value =
      caught.name === "AbortError"
        ? "The connection was closed."
        : caught.message;
    status.value = "";
  } finally {
    clearInterval(timer);
    elapsed.value = Math.round(performance.now() - started);
    processing.value = false;
  }
}
onBeforeUnmount(() => {
  controller?.abort();
  clearInterval(timer);
});
</script>

<template>
  <section class="documents-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">Extract. Inspect. Review.</p>
        <h1>Documents</h1>
        <p>
          Extract structured fields and review the details that need attention.
        </p>
      </div>
      <span class="context-label"
        ><AppIcon name="shield" :size="15" />Human review stays in the
        loop</span
      >
    </header>
    <div class="documents-layout">
      <div class="document-intake">
        <section class="surface intake-card">
          <div class="section-heading">
            <div>
              <h2>New document job</h2>
              <p>Identity documents and supported application forms.</p>
            </div>
          </div>
          <input
            ref="input"
            class="sr-only"
            type="file"
            multiple
            accept=".pdf,.jpg,.jpeg,.png,.webp"
            aria-label="Choose documents to process"
            :disabled="processing"
            @change="selectFiles"
          />
          <div
            class="document-dropzone"
            :class="{ dragging: dragActive }"
            @dragover.prevent="dragActive = true"
            @dragleave.prevent="dragActive = false"
            @drop.prevent="
              dragActive = false;
              !processing && addFiles($event.dataTransfer.files);
            "
          >
            <span class="icon-tile"><AppIcon name="files" :size="26" /></span>
            <h3>Drop your documents here</h3>
            <p>PDF, JPEG, PNG, or WebP</p>
            <button
              class="button secondary"
              :disabled="processing"
              @click="input?.click()"
            >
              <AppIcon name="plus" :size="15" />Choose files</button
            ><small>Up to 20 files · 20 MB each · 50 pages per PDF</small>
          </div>
          <ul v-if="files.length" class="selected-files">
            <li v-for="(file, index) in files" :key="file.name + index">
              <AppIcon name="file" :size="17" />
              <div>
                <b>{{ file.name }}</b
                ><small>{{ formatBytes(file.size) }}</small>
              </div>
              <button
                class="icon-button"
                :disabled="processing"
                :aria-label="'Remove ' + file.name"
                @click="
                  files.splice(index, 1);
                  consent = false;
                "
              >
                <AppIcon name="close" :size="14" />
              </button>
            </li>
          </ul>
          <label class="document-consent"
            ><input
              v-model="consent"
              type="checkbox"
              :disabled="processing || !files.length"
            /><span
              >Allow these documents to be processed by the configured external
              OCR/AI services.</span
            ></label
          ><button
            class="button primary full-width"
            :disabled="processing || !files.length || !consent"
            @click="process"
          >
            <span v-if="processing" class="spinner" /><AppIcon
              v-else
              name="play"
              :size="15"
            />{{ processing ? "Processing documents…" : "Process documents" }}
          </button>
          <p v-if="error" class="notice error" role="alert">{{ error }}</p>
        </section>
        <section v-if="savedJobs.length" class="surface recent-jobs">
          <div class="section-heading">
            <h2>Recent jobs</h2>
            <span class="subtle-label">This browser</span>
          </div>
          <button
            v-for="job in savedJobs"
            :key="job.job_id"
            :class="['recent-job', { active: result?.job_id === job.job_id }]"
            :disabled="processing"
            @click="result = job"
          >
            <span class="file-icon"><AppIcon name="file" :size="17" /></span
            ><span
              ><b
                >{{ job.document_count }} document{{
                  job.document_count === 1 ? "" : "s"
                }}</b
              ><small>{{ formatDate(job.createdAt) }}</small></span
            ><span
              class="job-flag-count"
              :class="{ flagged: job.review_report?.flagged_fields?.length }"
              >{{ job.review_report?.flagged_fields?.length || 0 }} flags</span
            >
          </button>
        </section>
      </div>
      <section class="surface document-review">
        <header class="review-heading">
          <div>
            <h2>
              {{
                processing
                  ? "Processing your documents"
                  : result
                    ? "Extraction review"
                    : "Your review workspace"
              }}
            </h2>
            <p>
              {{
                result
                  ? formatDate(result.createdAt)
                  : "Results appear here when processing finishes."
              }}
            </p>
          </div>
          <span v-if="processing" class="latency">{{
            formatLatency(elapsed)
          }}</span
          ><span
            v-else-if="result"
            class="status-tag"
            :class="{ warning: flags.length }"
            >{{ flags.length ? "Review needed" : "Review ready" }}</span
          >
        </header>
        <div v-if="processing" class="document-processing">
          <span class="spinner large" />
          <h3>{{ status }}</h3>
          <p>Progress comes directly from the processing service.</p>
          <ol class="processing-log">
            <li v-for="(step, index) in progress" :key="index">
              <AppIcon name="check" :size="14" />{{ step }}
            </li>
          </ol>
        </div>
        <div v-else-if="!result" class="document-review-empty">
          <div class="review-art" aria-hidden="true">
            <AppIcon name="file" :size="48" /><span
              ><AppIcon name="check" :size="18"
            /></span>
          </div>
          <h2>Every field has a story.</h2>
          <p>
            Upload your documents to see extracted values, confidence scores,
            and fields flagged for human review.
          </p>
          <div class="review-features">
            <span><AppIcon name="search" :size="16" />Traceable extraction</span
            ><span
              ><AppIcon name="shield" :size="16" />Visible review flags</span
            ><span
              ><AppIcon name="download" :size="16" />Downloadable outputs</span
            >
          </div>
        </div>
        <template v-else>
          <div class="document-metrics">
            <span
              ><b>{{ result.document_count }}</b
              >Documents</span
            ><span
              ><b>{{ result.page_count }}</b
              >Pages</span
            ><span :class="{ 'text-warning': flags.length }"
              ><b>{{ flags.length }}</b
              >Review flags</span
            ><span class="latency"
              ><b>{{ formatLatency(result.latency_ms) || "—" }}</b
              >Processing time</span
            >
          </div>
          <div class="output-downloads">
            <a
              v-for="(url, name) in result.outputs"
              :key="name"
              :href="url"
              target="_blank"
              rel="noopener noreferrer"
              class="button secondary"
              ><AppIcon name="download" :size="14" />{{
                outputNames[name] || label(name)
              }}</a
            >
          </div>
          <p v-if="result.review_report?.summary" class="review-summary">
            {{ result.review_report.summary }}
          </p>
          <details v-if="flags.length" class="review-flags">
            <summary>
              <AppIcon name="alert" :size="16" />{{ flags.length }} field{{
                flags.length === 1 ? "" : "s"
              }}
              need attention<AppIcon name="down" :size="14" />
            </summary>
            <ul>
              <li v-for="(flag, index) in flags" :key="index">
                <b>{{
                  label(
                    flag.field ||
                      flag.field_name ||
                      flag.document_type ||
                      "Field",
                  )
                }}</b
                ><span>{{
                  label(flag.reason || "Human review required")
                }}</span>
              </li>
            </ul>
          </details>
          <article
            v-for="(document, index) in result.documents"
            :key="document.document_id || index"
            class="extracted-document"
          >
            <header>
              <span class="file-icon"><AppIcon name="file" :size="17" /></span>
              <div>
                <h3>
                  {{
                    label(document.document_type) || "Document " + (index + 1)
                  }}
                </h3>
                <p>
                  {{ label(extractionFor(document).text_medium) }} ·
                  {{ label(document.processor_route) }}
                </p>
              </div>
              <span
                class="status-tag"
                :class="{
                  warning:
                    extractionFor(document).system_evaluation_matrix
                      ?.final_routing_decision === 'HUMAN_REVIEWS_REQUIRED',
                }"
                >{{
                  extractionFor(document).system_evaluation_matrix
                    ?.final_routing_decision === "HUMAN_REVIEWS_REQUIRED"
                    ? "Review required"
                    : "Extracted"
                }}</span
              >
            </header>
            <p v-if="document.error" class="notice error">
              {{ document.error }}
            </p>
            <details
              v-if="document.extraction_attempts?.length"
              class="execution-details"
            >
              <summary>Extraction attempts</summary>
              <ol>
                <li
                  v-for="(
                    attempt, attemptIndex
                  ) in document.extraction_attempts"
                  :key="attemptIndex"
                >
                  {{ label(attempt.method) }} · {{ label(attempt.status) }}
                  <template v-if="attempt.review_items !== undefined">
                    · {{ attempt.review_items }} review item(s)</template
                  >
                  <template v-if="attempt.error_type">
                    · {{ attempt.error_type }}</template
                  >
                </li>
              </ol>
            </details>
            <div class="simple-table-wrap">
              <table class="simple-table extraction-table">
                <thead>
                  <tr>
                    <th>Field</th>
                    <th>Extracted value</th>
                    <th>Confidence</th>
                    <th>Review</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="field in fieldsFor(document)" :key="field.name">
                    <td>{{ label(field.name) }}</td>
                    <td :class="{ 'text-muted': !field.value }">
                      {{ fieldValue(field.value) }}
                    </td>
                    <td>
                      {{
                        formatConfidence(
                          field.final_field_score ?? field.ai_confidence,
                        )
                      }}
                    </td>
                    <td>
                      <span
                        class="status-tag"
                        :class="{ warning: field.requires_human_review }"
                        >{{
                          field.requires_human_review ? "Required" : "No flag"
                        }}</span
                      >
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <details class="raw-output">
              <summary>View structured output</summary>
              <pre>{{ JSON.stringify(document, null, 2) }}</pre>
            </details>
          </article>
        </template>
      </section>
    </div>
  </section>
</template>
