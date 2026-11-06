<script setup>
import { onBeforeUnmount, ref, watch } from "vue";
import { preferences, savePreferences } from "../preferences.js";
import AppIcon from "../components/AppIcon.vue";
const saved = ref(false);
const error = ref("");
let timer;
watch(
  preferences,
  () => {
    try {
      savePreferences();
      saved.value = true;
      error.value = "";
      clearTimeout(timer);
      timer = setTimeout(() => {
        saved.value = false;
      }, 2000);
    } catch {
      error.value = "This browser could not save your preferences.";
    }
  },
  { deep: true },
);
onBeforeUnmount(() => clearTimeout(timer));
</script>
<template>
  <section class="preferences-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">Make the workspace yours</p>
        <h1>Preferences</h1>
        <p>Choose how information is presented in this browser.</p>
      </div>
      <span v-if="saved" class="status-tag" role="status"
        ><AppIcon name="check" :size="13" />Saved</span
      >
    </header>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <section class="surface preferences-card">
      <div class="preferences-section-title">
        <span class="icon-tile small"><AppIcon name="sparkle" /></span>
        <div>
          <h2>Analysis experience</h2>
          <p>Keep the information that matters in view.</p>
        </div>
      </div>
      <label class="preference-row"
        ><div>
          <b>Live activity</b>
          <p>
            Show streamed execution updates while the agent works. Latency
            remains visible.
          </p>
        </div>
        <span class="switch"
          ><input
            v-model="preferences.liveUpdates"
            type="checkbox"
            role="switch"
            aria-label="Show live activity" /><span /></span
      ></label>
      <label class="preference-row"
        ><div>
          <b>Source evidence</b>
          <p>
            Show the citations returned with an answer, alongside its confidence
            score.
          </p>
        </div>
        <span class="switch"
          ><input
            v-model="preferences.citations"
            type="checkbox"
            role="switch"
            aria-label="Show source evidence" /><span /></span
      ></label>
      <label class="preference-row"
        ><div>
          <b>Compact spreadsheet</b>
          <p>Use shorter rows to see more of your workbook at once.</p>
        </div>
        <span class="switch"
          ><input
            v-model="preferences.compactTables"
            type="checkbox"
            role="switch"
            aria-label="Compact spreadsheet rows" /><span /></span
      ></label>
      <footer class="preferences-footer">
        <AppIcon name="check" :size="14" />Changes save automatically in this
        browser.
      </footer>
    </section>
    <section class="preferences-note">
      <AppIcon name="shield" :size="18" />
      <p>
        AI processing consent is managed in the workspace for each uploaded
        workbook. Workbook edits still require approval of their preview.
      </p>
    </section>
  </section>
</template>
