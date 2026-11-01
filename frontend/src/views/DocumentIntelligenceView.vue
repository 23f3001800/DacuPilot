<script setup>
import { ref } from "vue";

const files = ref([]);
const consent = ref(false);
const processing = ref(false);
const status = ref("");
const error = ref("");
const result = ref(null);
const savedJobs = ref([]);
const selectedJob = ref(null);
try { savedJobs.value = JSON.parse(localStorage.getItem("insightpilot-document-jobs") || "[]"); } catch { savedJobs.value = []; }

function selectFiles(event) {
  files.value = Array.from(event.target.files || []);
  error.value = "";
  result.value = null;
}

async function processDocuments() {
  if (!files.value.length || !consent.value || processing.value) return;
  processing.value = true;
  status.value = "Uploading documents...";
  error.value = "";
  const body = new FormData();
  files.value.forEach((file) => body.append("files", file));
  body.set("external_processing_consent", "true");
  try {
    const response = await fetch("/api/documents/process/stream", { method: "POST", body });
    if (!response.ok || !response.body) throw new Error("Document processing request failed.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const events = buffer.replace(/\r\n/g, "\n").split("\n\n");
      buffer = events.pop() || "";
      for (const raw of events) {
        const line = raw.split("\n").find((item) => item.startsWith("data: "));
        if (!line) continue;
        const event = JSON.parse(line.slice(6));
        if (event.type === "progress") status.value = event.message || event.stage || "Processing...";
        if (event.type === "complete") {
          result.value = event.result;
          status.value = "Processing complete.";
          const entry = { ...event.result, createdAt: new Date().toISOString() };
          savedJobs.value = [entry, ...savedJobs.value.filter((job) => job.job_id !== entry.job_id)].slice(0, 30);
          localStorage.setItem("insightpilot-document-jobs", JSON.stringify(savedJobs.value));
        }
        if (event.type === "error") throw new Error(event.message || "Document processing failed.");
      }
      if (done) break;
    }
  } catch (caught) {
    error.value = caught.message;
    status.value = "";
  } finally {
    processing.value = false;
  }
}
</script>

<template>
  <section class="workflow-view">
    <div class="view-heading"><div><p class="eyebrow">DocuLens · document intelligence</p><h1>Document Workspace</h1><p>Process documents, review traceable extraction results, and revisit recent jobs.</p></div><span v-if="status" class="status-pill">{{ status }}</span></div>
    <section class="panel">
      <h2>Process documents</h2>
      <input type="file" multiple @change="selectFiles" />
      <p class="helper">{{ files.length }} file(s) selected. Maximum 20 files per job.</p>
      <label class="consent-row"><input v-model="consent" type="checkbox" /> I consent to sending these documents to the configured external OCR/AI service.</label>
      <button class="primary-button" :disabled="processing || !files.length || !consent" @click="processDocuments">{{ processing ? "Processing..." : "Process documents" }}</button>
      <p v-if="error" class="error-message">{{ error }}</p>
    </section>
    <section v-if="result" class="panel result-panel">
      <h2>Job results</h2>
      <div class="result-grid"><span>Documents: <strong>{{ result.document_count }}</strong></span><span>Pages: <strong>{{ result.page_count }}</strong></span><span>Latency: <strong>{{ result.latency_ms ?? "n/a" }} ms</strong></span><span>Review flags: <strong>{{ result.review_report?.flagged_fields?.length ?? 0 }}</strong></span></div>
      <p class="helper">{{ result.review_report?.summary || "No review summary returned." }}</p>
      <div class="download-row"><a v-for="(url, name) in result.outputs" :key="name" class="download-link" :href="url" target="_blank" rel="noreferrer">{{ name }}</a></div>
    </section>
    <section v-if="savedJobs.length" class="panel result-panel"><div class="panel-heading"><div><h2>Recent processing jobs</h2><p class="helper">Saved in this browser for quick access.</p></div></div><div class="document-job-list"><button v-for="job in savedJobs" :key="job.job_id" class="document-job-row" @click="selectedJob = job; result = job"><span class="job-status-dot" /><span><b>{{ job.document_count }} document(s) processed</b><small>{{ new Date(job.createdAt).toLocaleString() }} · {{ job.page_count }} pages</small></span><strong>{{ job.review_report?.flagged_fields?.length ?? 0 }} review flags</strong></button></div></section>
    <section v-if="selectedJob?.documents?.length" class="panel result-panel"><div class="panel-heading"><div><h2>Extracted document details</h2><p class="helper">Inspect extracted fields from the selected job.</p></div><button class="text-button" @click="selectedJob = null">Close</button></div><article v-for="(document, index) in selectedJob.documents" :key="document.document_id || index" class="extracted-document"><h3>{{ document.filename || document.name || `Document ${index + 1}` }}</h3><pre>{{ JSON.stringify(document, null, 2) }}</pre></article></section>
  </section>
</template>
