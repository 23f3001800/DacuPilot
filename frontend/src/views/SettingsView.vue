<script setup>
import { onMounted, ref, watch } from "vue";
import { loadPreferences, preferences, savePreferences } from "../preferences.js";

const saved = ref(false);
let savedTimer;

onMounted(loadPreferences);
watch(preferences, () => {
  savePreferences();
  saved.value = true;
  clearTimeout(savedTimer);
  savedTimer = setTimeout(() => { saved.value = false; }, 1800);
}, { deep: true });
</script>

<template>
  <section class="product-page settings-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">Workspace controls</p>
        <h1>Settings</h1>
        <p class="page-lead">Choose how the Data Analysis Agent presents activity, evidence, and workbook data.</p>
      </div>
      <span v-if="saved" class="saved-tag" role="status">Saved</span>
    </div>
    <section class="panel settings-card">
      <div class="settings-row">
        <div><b>Live agent updates</b><p>Show streamed tool progress and the live latency counter while workbook analysis runs.</p></div>
        <input v-model="preferences.liveUpdates" aria-label="Live agent updates" type="checkbox" />
      </div>
      <div class="settings-row">
        <div><b>Show source citations</b><p>Display evidence citations when available. Confidence and latency remain visible when the agent returns them.</p></div>
        <input v-model="preferences.citations" aria-label="Show source citations" type="checkbox" />
      </div>
      <div class="settings-row">
        <div><b>Compact workbook tables</b><p>Reduce row height when inspecting the workbook preview.</p></div>
        <input v-model="preferences.compactTables" aria-label="Compact workbook tables" type="checkbox" />
      </div>
      <p class="helper">Preferences save automatically in this browser.</p>
    </section>
  </section>
</template>
