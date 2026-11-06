<script setup>
import AppIcon from "./AppIcon.vue";
import { formatConfidence, formatLatency } from "../lib/format.js";
import { preferences } from "../preferences.js";
defineProps({
  confidence: { type: [Number, String], default: null },
  latencyMs: { type: [Number, String], default: null },
  citations: { type: Array, default: () => [] },
  rationale: { type: String, default: "" },
});
const sourceLabel = (source) =>
  typeof source === "string"
    ? source
    : source.title || source.source || "Workbook evidence";
</script>
<template>
  <div class="answer-metadata">
    <div class="answer-stats">
      <span v-if="formatLatency(latencyMs)" class="latency"
        ><AppIcon name="clock" :size="13" />{{ formatLatency(latencyMs) }}</span
      >
      <span
        class="confidence-label"
        :title="
          rationale || 'Heuristic evidence score; not a calibrated probability.'
        "
        >Confidence <b>{{ formatConfidence(confidence) }}</b></span
      >
    </div>
    <details
      v-if="rationale || (preferences.citations && citations.length)"
      class="answer-evidence"
    >
      <summary>
        {{
          preferences.citations && citations.length
            ? citations.length +
              (citations.length === 1 ? " source" : " sources")
            : "About this score"
        }}<AppIcon name="down" :size="12" />
      </summary>
      <div class="evidence-content">
        <p v-if="rationale">{{ rationale }}</p>
        <ul v-if="preferences.citations && citations.length">
          <li v-for="(source, index) in citations" :key="index">
            <a
              v-if="source.url"
              :href="source.url"
              target="_blank"
              rel="noopener noreferrer"
              >{{ sourceLabel(source) }}<AppIcon name="external" :size="12"
            /></a>
            <b v-else>{{ sourceLabel(source) }}</b>
            <small v-if="source.detail">{{ source.detail }}</small>
          </li>
        </ul>
      </div>
    </details>
  </div>
</template>
