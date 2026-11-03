<script setup>
import { onMounted, ref } from "vue";
import { getHealth, streamAssistant } from "./api";
import DataAgentView from "./views/DataAgentView.vue";
import DocumentIntelligenceView from "./views/DocumentIntelligenceView.vue";
import HomeView from "./views/HomeView.vue";
import AnalyticsView from "./views/AnalyticsView.vue";
import DashboardView from "./views/DashboardView.vue";
import WorkflowView from "./views/WorkflowView.vue";
import SettingsView from "./views/SettingsView.vue";
import ReportsView from "./views/ReportsView.vue";
import { loadPreferences } from "./preferences.js";

const routes = [
  { id: "home", label: "Overview", icon: "⌂", hint: "Workspace overview" },
  { id: "data-agent", label: "Data", icon: "▤", hint: "Explore workbooks" },
  { id: "analytics", label: "Analysis", icon: "◒", hint: "Visual insights" },
  { id: "dashboards", label: "Dashboards", icon: "▦", hint: "Generated dashboards" },
  { id: "documents", label: "DocuLens", icon: "▣", hint: "Upload and extract" },
  { id: "workflows", label: "Agent Workflows", icon: "⟳", hint: "Run workbook automation" },
  { id: "reports", label: "Reports", icon: "▤", hint: "Saved agent outputs" },
  { id: "settings", label: "Settings", icon: "⚙", hint: "Workspace preferences" },
];
const activeRoute = ref("home");
const dataAgentQuestion = ref("");
const globalQuery = ref("");
const online = ref(false);
const healthChecked = ref(false);
const assistantOpen = ref(false);
const assistantQuestion = ref("");
const assistantSending = ref(false);
const assistantStatus = ref("");
const assistantMessages = ref([]);
function getDocumentThreadId() {
  const stored = sessionStorage.getItem("datapilot-doc-thread-id");
  const valid = stored && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(stored);
  const threadId = valid ? stored : crypto.randomUUID();
  sessionStorage.setItem("datapilot-doc-thread-id", threadId);
  return threadId;
}
const assistantThread = ref(getDocumentThreadId());
const assistantElapsedMs = ref(0);

function navigate(request) {
  if (typeof request === "string") {
    activeRoute.value = request === "document-intelligence" ? "documents" : request;
    return;
  }
  activeRoute.value = request.id === "document-intelligence" ? "documents" : request.id;
  if (request.id === "data-agent" && request.query) dataAgentQuestion.value = request.query;
}

function searchWorkspace() {
  const query = globalQuery.value.trim();
  if (!query) return;
  const normalize = (value) => value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const normalized = normalize(query);
  const matchingRoute = routes.find((route) => {
    const labels = [route.label, route.hint, route.id.replace(/-/g, " ")].map(normalize);
    return labels.some((label) => label === normalized || normalized.length >= 4 && label.split(" ").some((word) => word.startsWith(normalized)));
  });
  if (matchingRoute) activeRoute.value = matchingRoute.id;
  else {
    dataAgentQuestion.value = query;
    activeRoute.value = "data-agent";
  }
  globalQuery.value = "";
}

function assistantConfidence(value) {
  if (value === null || value === undefined || value === "") return "Not scored";
  const score = Number(value);
  return Number.isFinite(score) ? `${Math.round(score <= 1 ? score * 100 : score)}%` : "Not provided";
}

async function askAssistant() {
  const text = assistantQuestion.value.trim();
  if (!text || assistantSending.value) return;
  assistantQuestion.value = "";
  assistantMessages.value.push({ role: "user", text });
  const answer = { role: "assistant", text: "", thinking: true, latencyMs: null, confidence: null, citations: [] };
  assistantMessages.value.push(answer);
  assistantSending.value = true;
  assistantStatus.value = "Thinking...";
  const startedAt = performance.now();
  assistantElapsedMs.value = 0;
  const latencyTimer = setInterval(() => { assistantElapsedMs.value = Math.round(performance.now() - startedAt); }, 100);
  try {
    await streamAssistant({ message: text, threadId: assistantThread.value, mode: "document-assistant", onEvent(event) {
      if (event.event === "token") answer.text += event.text || "";
      if (event.event === "status" || event.event === "tool_start") assistantStatus.value = event.text || "Working...";
      if (event.event === "final_answer") answer.text = event.text || answer.text;
      if (event.event === "latency" && Number.isFinite(Number(event.total_ms))) {
        answer.latencyMs = Number(event.total_ms);
        assistantElapsedMs.value = Math.round(answer.latencyMs);
      }
      if (event.event === "evaluation") {
        const metrics = event.payload || {};
        answer.confidence = event.confidence_score ?? metrics.confidence_score ?? null;
        answer.citations = (metrics.sources || []).map((source) => ({ source }));
      }
      if (event.event === "error") answer.text = event.details || "The Document Assistant could not answer. Please try again.";
      if (event.thread_id) { assistantThread.value = event.thread_id; sessionStorage.setItem("datapilot-doc-thread-id", event.thread_id); }
    }});
  } catch (error) { answer.text = error.message; }
  finally {
    clearInterval(latencyTimer);
    answer.latencyMs ??= Math.round(performance.now() - startedAt);
    assistantElapsedMs.value = Math.round(answer.latencyMs);
    answer.thinking = false;
    assistantSending.value = false;
    assistantStatus.value = "";
  }
}

onMounted(async () => {
  loadPreferences();
  try { await getHealth(); online.value = true; }
  catch { online.value = false; }
  finally { healthChecked.value = true; }
});
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand-lockup"><div class="brand-mark">▥</div><div class="brand-copy"><strong>InsightPilot</strong><span>Analyze · Transform · Insight</span></div></div>
      <nav class="topnav" aria-label="Main navigation"><button v-for="route in routes" :key="route.id" :class="['topnav-item', { active: activeRoute === route.id }]" :aria-current="activeRoute === route.id ? 'page' : undefined" @click="activeRoute = route.id">{{ route.label }}</button></nav>
      <div class="topbar-actions"><form class="global-search" role="search" @submit.prevent="searchWorkspace"><span>⌕</span><input v-model="globalQuery" aria-label="Search pages or data" placeholder="Search pages or ask about data..." /><button type="submit" aria-label="Search">↵</button></form><span class="agent-status" :class="{ online, offline: healthChecked && !online }" role="status" :aria-label="!healthChecked ? 'Checking backend status' : online ? 'Live agent active' : 'Backend offline'"><i aria-hidden="true" /><span>{{ !healthChecked ? 'Connecting…' : online ? 'Live Agent Active' : 'Backend Offline' }}</span></span><span class="notification" aria-label="Notifications">♧</span><span class="workspace-user" aria-label="Current workspace"><b>V</b></span></div>
    </header>
    <div class="workspace">
      <main class="content">
        <HomeView v-if="activeRoute === 'home'" @navigate="navigate" />
        <DataAgentView v-show="activeRoute === 'data-agent'" :initial-question="dataAgentQuestion" @clear-initial="dataAgentQuestion = ''" />
        <DocumentIntelligenceView v-if="activeRoute === 'documents'" />
        <AnalyticsView v-if="activeRoute === 'analytics'" />
        <DashboardView v-if="activeRoute === 'dashboards'" />
        <WorkflowView v-if="activeRoute === 'workflows'" />
        <ReportsView v-if="activeRoute === 'reports'" />
        <SettingsView v-if="activeRoute === 'settings'" />
      </main>
    </div>
    <button class="assistant-fab" :class="{ active: assistantOpen }" :aria-expanded="assistantOpen" aria-controls="document-assistant-drawer" :aria-label="assistantOpen ? 'Close Document Assistant' : 'Open Document Assistant'" :title="assistantOpen ? 'Close Document Assistant' : 'Document Assistant'" @click="assistantOpen = !assistantOpen"><span>✦</span><b>Document Assistant</b></button>
    <aside v-if="assistantOpen" id="document-assistant-drawer" class="assistant-drawer"><div class="drawer-head"><div><b>✦ Document Assistant</b><small><i /> General answers · Online</small></div><button aria-label="Close Document Assistant" @click="assistantOpen = false">×</button></div><div class="drawer-messages" aria-live="polite"><p v-if="!assistantMessages.length" class="drawer-empty">Ask general questions about documents, policies, and how to use this workspace.</p><div v-for="(message, index) in assistantMessages" :key="index" :class="['drawer-message', message.role]"><b>{{ message.role === 'user' ? 'You' : 'Document Assistant' }}</b><span v-if="message.thinking" class="drawer-thinking"><i /><i /><i /> {{ assistantStatus }} <strong>{{ assistantElapsedMs }} ms</strong></span><template v-else><p>{{ message.text }}</p><div v-if="message.role === 'assistant'" class="answer-meta"><span class="latency">Latency {{ message.latencyMs ?? 'n/a' }} ms</span><span>Confidence {{ assistantConfidence(message.confidence) }}</span></div><ul v-if="message.citations?.length" class="analysis-citations"><li v-for="citation in message.citations" :key="citation.source">{{ citation.source }}</li></ul></template></div></div><form class="drawer-form" @submit.prevent="askAssistant"><input v-model="assistantQuestion" placeholder="Ask a general question..." :disabled="assistantSending" /><button type="submit" :disabled="assistantSending || !assistantQuestion.trim()">→</button></form></aside>
  </div>
</template>
