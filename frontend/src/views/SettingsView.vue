<script setup>
import { ref } from "vue";
const saved = ref(false);
const settings = ref({ liveUpdates: true, citations: true, compactTables: false });
function save() { localStorage.setItem("datapilot-settings", JSON.stringify(settings.value)); saved.value = true; setTimeout(() => { saved.value = false; }, 1800); }
</script>

<template><section class="product-page settings-page"><div class="page-heading"><div><p class="eyebrow">Workspace controls</p><h1>Settings</h1><p class="page-lead">Tune how DocuPilot presents analysis and evidence.</p></div><span v-if="saved" class="saved-tag">Saved</span></div><section class="panel settings-card"><div class="settings-row"><div><b>Live agent updates</b><p>Show streamed thinking, tool progress, and latency while an answer is running.</p></div><input v-model="settings.liveUpdates" type="checkbox" /></div><div class="settings-row"><div><b>Show citations and confidence</b><p>Keep evidence and answer-quality metadata visible beneath every response.</p></div><input v-model="settings.citations" type="checkbox" /></div><div class="settings-row"><div><b>Compact workbook tables</b><p>Use denser rows when inspecting large Excel sheets.</p></div><input v-model="settings.compactTables" type="checkbox" /></div><button class="primary-button" @click="save">Save workspace settings</button></section></section></template>
