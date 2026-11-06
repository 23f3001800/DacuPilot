<script setup>
import { onBeforeUnmount, ref } from "vue";
import { streamWorkflow } from "../api";
import { getWorkspaceStorageKey } from "../workbookSession.js";
import { formatLatency, readStoredArray } from "../lib/format.js";
import AppIcon from "./AppIcon.vue";
const props = defineProps({ threadId: { type: String, required: true } });
const emit = defineEmits(["complete"]);
const stages = ref([
  { id: "receive", label: "Read workbook", state: "ready" },
  { id: "profile", label: "Profile columns", state: "ready" },
  { id: "analysis", label: "Generate charts", state: "ready" },
  { id: "response", label: "Prepare output", state: "ready" },
]);
const running = ref(false);
const output = ref(null);
const error = ref("");
const elapsed = ref(0);
let timer;
let controller;
async function run() {
  if (running.value) return;
  running.value = true;
  output.value = null;
  error.value = "";
  stages.value.forEach((stage) => {
    stage.state = "ready";
  });
  const started = performance.now();
  controller = new AbortController();
  timer = setInterval(() => {
    elapsed.value = Math.round(performance.now() - started);
  }, 100);
  try {
    await streamWorkflow({
      threadId: props.threadId,
      signal: controller.signal,
      onEvent(event) {
        if (event.event === "stage") {
          const stage = stages.value.find((item) => item.id === event.stage);
          if (stage) stage.state = event.state;
        }
        if (event.event === "result") output.value = event.result;
        if (event.event === "error")
          throw new Error(event.message || "The profile could not complete.");
      },
    });
    if (!output.value)
      throw new Error("The server did not return a profile. Please try again.");
    const key = getWorkspaceStorageKey(
      "insightpilot-workflow-runs",
      props.threadId,
    );
    try {
      localStorage.setItem(
        key,
        JSON.stringify(
          [
            {
              ...output.value,
              id: crypto.randomUUID(),
              createdAt: new Date().toISOString(),
            },
            ...readStoredArray(key),
          ].slice(0, 30),
        ),
      );
    } catch {
      error.value =
        "The profile completed, but this browser could not save its run history.";
    }
    emit("complete");
  } catch (caught) {
    error.value =
      caught.name === "AbortError" ? "Profile stopped." : caught.message;
    stages.value.forEach((stage) => {
      if (stage.state === "active") stage.state = "error";
    });
  } finally {
    clearInterval(timer);
    elapsed.value = Math.round(performance.now() - started);
    running.value = false;
  }
}
onBeforeUnmount(() => {
  controller?.abort();
  clearInterval(timer);
});
</script>
<template>
  <section class="profile-run">
    <div class="section-heading">
      <div>
        <h3>Quick workbook profile</h3>
        <p>Inspect data quality and generate charts from numeric fields.</p>
      </div>
      <button class="button secondary" :disabled="running" @click="run">
        <AppIcon name="play" :size="14" />{{
          running ? "Profiling…" : output ? "Run again" : "Run profile"
        }}
      </button>
    </div>
    <ol v-if="running || output || error" class="run-steps">
      <li v-for="(stage, index) in stages" :key="stage.id" :class="stage.state">
        <span>{{ stage.state === "done" ? "✓" : index + 1 }}</span
        >{{ stage.label }}
      </li>
    </ol>
    <p v-if="running" class="thinking-line">
      <span class="spinner" /><span>Working on the active workbook</span
      ><b class="latency">{{ formatLatency(elapsed) }}</b>
    </p>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <div v-if="output" class="profile-result">
      <AppIcon name="check" :size="16" />
      <p>{{ output.summary }}</p>
      <span class="latency">{{ formatLatency(elapsed) }}</span>
    </div>
  </section>
</template>
