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

const routes = [
  { id: "home", label: "Overview", icon: "⌂", hint: "Workspace overview" },
  { id: "data-agent", label: "Data", icon: "▤", hint: "Explore workbooks" },
  { id: "analytics", label: "Analysis", icon: "◒", hint: "Visual insights" },
  { id: "dashboards", label: "Dashboards", icon: "▦", hint: "Generated dashboards" },
  { id: "documents", label: "DocuLens", icon: "▣", hint: "Upload and extract" },
  { id: "workflows", label: "Reports", icon: "▤", hint: "Agent outputs" },
];
const activeRoute = ref("home");
const online = ref(false);
const assistantOpen = ref(false);
const assistantQuestion = ref("");
const assistantSending = ref(false);
const assistantStatus = ref("");
const assistantMessages = ref([]);
const assistantThread = ref(sessionStorage.getItem("datapilot-doc-thread-id") || crypto.randomUUID());

async function askAssistant() {
  const text = assistantQuestion.value.trim();
  if (!text || assistantSending.value) return;
  assistantQuestion.value = "";
  assistantMessages.value.push({ role: "user", text });
  assistantMessages.value.push({ role: "assistant", text: "", thinking: true });
  assistantSending.value = true;
  assistantStatus.value = "Thinking...";
  try {
    await streamAssistant({ message: text, threadId: assistantThread.value, mode: "document-assistant", onEvent(event) {
      const current = assistantMessages.value.at(-1);
      if (event.event === "token") current.text += event.text || "";
      if (event.event === "status" || event.event === "tool_start") assistantStatus.value = event.text || "Working...";
      if (event.event === "final_answer") current.text = event.text || current.text;
      if (event.thread_id) { assistantThread.value = event.thread_id; sessionStorage.setItem("datapilot-doc-thread-id", event.thread_id); }
    }});
  } catch (error) { assistantMessages.value.at(-1).text = error.message; }
  finally { assistantMessages.value.at(-1).thinking = false; assistantSending.value = false; assistantStatus.value = ""; }
}

onMounted(async () => { try { await getHealth(); online.value = true; } catch { online.value = false; } });
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand-lockup"><div class="brand-mark">▥</div><div class="brand-copy"><strong>InsightPilot</strong><span>Analyze · Transform · Insight</span></div></div>
      <nav class="topnav" aria-label="Main navigation"><button v-for="route in routes" :key="route.id" :class="['topnav-item', { active: activeRoute === route.id }]" @click="activeRoute = route.id">{{ route.label }}</button></nav>
      <div class="topbar-actions"><label class="global-search"><span>⌕</span><input aria-label="Global search" placeholder="Search..." /></label><span class="notification">♧</span><span class="workspace-user"><b>V</b></span></div>
    </header>
    <div class="workspace">
      <main class="content">
        <HomeView v-if="activeRoute === 'home'" @navigate="activeRoute = $event === 'document-intelligence' ? 'documents' : $event" />
        <DataAgentView v-show="activeRoute === 'data-agent'" />
        <DocumentIntelligenceView v-if="activeRoute === 'documents'" />
        <AnalyticsView v-if="activeRoute === 'analytics'" />
        <DashboardView v-if="activeRoute === 'dashboards'" />
        <ReportsView v-if="activeRoute === 'workflows'" />
        <SettingsView v-if="activeRoute === 'settings'" />
      </main>
    </div>
    <button class="assistant-fab" :class="{ active: assistantOpen }" aria-label="Open Document Assistant" title="Open Document Assistant" @click="assistantOpen = !assistantOpen">✦</button>
    <aside v-if="assistantOpen" class="assistant-drawer"><div class="drawer-head"><div><b>✦ Document Assistant</b><small><i /> General answers · Online</small></div><button @click="assistantOpen = false">×</button></div><div class="drawer-messages" aria-live="polite"><p v-if="!assistantMessages.length" class="drawer-empty">Ask general questions about documents, policies, and how to use this workspace.</p><div v-for="(message, index) in assistantMessages" :key="index" :class="['drawer-message', message.role]"><b>{{ message.role === 'user' ? 'You' : 'Document Assistant' }}</b><span v-if="message.thinking" class="thinking"><i /><i /><i /> {{ assistantStatus }}</span><p v-else>{{ message.text }}</p></div></div><form class="drawer-form" @submit.prevent="askAssistant"><input v-model="assistantQuestion" placeholder="Ask a general question..." :disabled="assistantSending" /><button type="submit" :disabled="assistantSending || !assistantQuestion.trim()">→</button></form></aside>
  </div>
</template>
