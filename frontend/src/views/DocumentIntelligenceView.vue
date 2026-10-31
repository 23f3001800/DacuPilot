<script setup>
import { ref } from "vue";

const files = ref([]);
const consent = ref(false);
const processing = ref(false);
const status = ref("");
const error = ref("");
const result = ref(null);

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
        if (event.type === "complete") { result.value = event.result; status.value = "Processing complete."; }
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
    <div class="view-heading"><div><p class="eyebrow">Structured extraction</p><h1>Document Intelligence</h1><p>Process documents, review uncertain fields, and download structured outputs.</p></div><span v-if="status" class="status-pill">{{ status }}</span></div>
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
  </section>
</template>
