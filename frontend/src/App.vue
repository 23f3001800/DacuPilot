<script setup>
import { onMounted, ref } from "vue";
import { getHealth } from "./api";
import DataAgentView from "./views/DataAgentView.vue";
import DocumentAssistantView from "./views/DocumentAssistantView.vue";
import DocumentIntelligenceView from "./views/DocumentIntelligenceView.vue";
import HomeView from "./views/HomeView.vue";

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
      <div class="brand-mark">&#9638;</div><div class="brand-copy"><strong>DocuPilot</strong><span>Intelligent Document and Data Processing</span></div>
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
        <HomeView v-if="activeRoute === 'home'" @navigate="activeRoute = $event" />
        <DataAgentView v-else-if="activeRoute === 'data-agent'" />
        <DocumentAssistantView v-else-if="activeRoute === 'document-assistant'" />
        <DocumentIntelligenceView v-else-if="activeRoute === 'document-intelligence'" />
        <template v-else>
          <p class="eyebrow">Vue migration foundation</p>
          <h1>{{ routes.find((route) => route.id === activeRoute)?.label }}</h1>
          <p>The legacy HTML workflow remains available while this Vue client is migrated feature by feature.</p>
        </template>
      </main>
    </div>
  </div>
</template>
