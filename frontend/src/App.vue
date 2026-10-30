<script setup>
import { onMounted, ref } from "vue";
import { getHealth } from "./api";

const routes = [
  { id: "home", label: "Home" },
  { id: "data-agent", label: "Data Agent" },
  { id: "document-assistant", label: "Document Assistant" },
  { id: "document-intelligence", label: "Document Intelligence" },
];
const activeRoute = ref("home");
const online = ref(false);

onMounted(async () => {
  try {
    await getHealth();
    online.value = true;
  } catch {
    online.value = false;
  }
});
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <strong>? DataPilot</strong>
      <span :class="['status', { offline: !online }]">
        <span class="status-dot" />{{ online ? "System Online" : "System Offline" }}
      </span>
    </header>
    <div class="workspace">
      <nav class="sidebar" aria-label="Main navigation">
        <button v-for="route in routes" :key="route.id" :class="['nav-item', { active: activeRoute === route.id }]" @click="activeRoute = route.id">
          {{ route.label }}
        </button>
      </nav>
      <main class="content">
