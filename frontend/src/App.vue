<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { getHealth } from "./api";
import { loadPreferences } from "./preferences.js";
import AppIcon from "./components/AppIcon.vue";
import CompanyHelp from "./components/CompanyHelp.vue";
import WorkspaceView from "./views/WorkspaceView.vue";
import ResultsView from "./views/ResultsView.vue";
import DocumentsView from "./views/DocumentsView.vue";
import SettingsView from "./views/SettingsView.vue";

loadPreferences();
const routes = [
  { id: "workspace", label: "Workspace", icon: "table" },
  { id: "results", label: "Results", icon: "chart" },
  { id: "documents", label: "Documents", icon: "files" },
];
const aliases = {
  home: "workspace",
  "data-agent": "workspace",
  analytics: "results",
  dashboards: "results",
  reports: "results",
  workflows: "workspace",
  "document-intelligence": "documents",
};
function routeFromHash() {
  const value = window.location.hash.replace(/^#\/?/, "");
  const route = aliases[value] || value;
  return [...routes.map((item) => item.id), "settings"].includes(route)
    ? route
    : null;
}
const activeRoute = ref(routeFromHash() || "workspace");
const initialQuestion = ref("");
const online = ref(false);
const healthChecked = ref(false);
const checkingHealth = ref(false);
const main = ref(null);
let healthTimer;
let healthController;

async function checkHealth() {
  if (checkingHealth.value) return;
  checkingHealth.value = true;
  healthController = new AbortController();
  const timeout = setTimeout(() => healthController.abort(), 6000);
  try {
    await getHealth(healthController.signal);
    online.value = true;
  } catch {
    online.value = false;
  } finally {
    clearTimeout(timeout);
    healthChecked.value = true;
    checkingHealth.value = false;
  }
}
function syncRoute() {
  const route = routeFromHash();
  if (!route) return;
  activeRoute.value = route;
  nextTick(() => main.value?.focus({ preventScroll: true }));
}
function navigate(request) {
  const id = aliases[request.id] || request.id;
  if (request.query) initialQuestion.value = request.query;
  activeRoute.value = id;
  if (window.location.hash !== "#/" + id) window.location.hash = "/" + id;
}
onMounted(() => {
  window.addEventListener("hashchange", syncRoute);
  checkHealth();
  healthTimer = setInterval(checkHealth, 30000);
});
onBeforeUnmount(() => {
  window.removeEventListener("hashchange", syncRoute);
  clearInterval(healthTimer);
  healthController?.abort();
});
</script>

<template>
  <div class="app-shell">
    <a class="skip-link" href="#main-content">Skip to content</a>
    <header class="app-header">
      <a class="brand" href="#/workspace" aria-label="InsightPilot workspace"
        ><span class="brand-mark"><AppIcon name="logo" :size="24" /></span
        ><strong>InsightPilot</strong></a
      >
      <nav class="main-nav" aria-label="Main navigation">
        <a
          v-for="route in routes"
          :key="route.id"
          :href="'#/' + route.id"
          :class="{ active: activeRoute === route.id }"
          :aria-current="activeRoute === route.id ? 'page' : undefined"
          ><AppIcon :name="route.icon" :size="16" /><span>{{
            route.label
          }}</span></a
        >
      </nav>
      <div class="header-tools">
        <button
          class="connection-state"
          :class="{ online, offline: healthChecked && !online }"
          :title="
            online
              ? 'Backend connected. Click to check again.'
              : 'Click to retry the backend connection.'
          "
          :disabled="checkingHealth"
          @click="checkHealth"
        >
          <i :class="{ pulsing: checkingHealth }" /><span>{{
            !healthChecked ? "Connecting" : online ? "Connected" : "Offline"
          }}</span></button
        ><span class="header-divider" /><a
          href="#/settings"
          class="icon-button"
          :class="{ selected: activeRoute === 'settings' }"
          aria-label="Workspace preferences"
          title="Preferences"
          ><AppIcon name="settings" :size="19"
        /></a>
      </div>
    </header>
    <main
      id="main-content"
      ref="main"
      tabindex="-1"
      class="app-content"
      :class="{ 'workspace-route': activeRoute === 'workspace' }"
    >
      <WorkspaceView
        v-show="activeRoute === 'workspace'"
        :active="activeRoute === 'workspace'"
        :initial-question="initialQuestion"
        @clear-initial="initialQuestion = ''"
      />
      <ResultsView
        v-show="activeRoute === 'results'"
        :active="activeRoute === 'results'"
        @navigate="navigate"
      />
      <DocumentsView v-show="activeRoute === 'documents'" />
      <SettingsView v-if="activeRoute === 'settings'" />
    </main>
    <CompanyHelp :online="online" />
  </div>
</template>
