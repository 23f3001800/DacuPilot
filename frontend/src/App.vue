<script setup>
import { onMounted, ref } from "vue";
import { getHealth, streamAssistant } from "./api";
import DataAgentView from "./views/DataAgentView.vue";
import DocumentIntelligenceView from "./views/DocumentIntelligenceView.vue";
import HomeView from "./views/HomeView.vue";
import AnalyticsView from "./views/AnalyticsView.vue";
import WorkflowView from "./views/WorkflowView.vue";
import SettingsView from "./views/SettingsView.vue";

const routes = [
  { id: "home", label: "Home", icon: "⌂", hint: "Workspace overview" },
  { id: "documents", label: "Documents", icon: "▣", hint: "Upload and extract" },
  { id: "data-agent", label: "Data Studio", icon: "▤", hint: "Explore workbooks" },
  { id: "analytics", label: "Analytics", icon: "◒", hint: "Visual insights" },
  { id: "workflows", label: "Agent Workflows", icon: "✣", hint: "Automate tasks" },
  { id: "settings", label: "Settings", icon: "⚙", hint: "Workspace controls" },
];
const activeRoute = ref("home");
const online = ref(false);
const assistantOpen = ref(false);
const assistantQuestion = ref("");
const assistantSending = ref(false);
const assistantStatus = ref("");
const assistantMessages = ref([]);
const assistantThread = ref(sessionStorage.getItem("datapilot-global-thread") || crypto.randomUUID());

async function askAssistant() {
  const text = assistantQuestion.value.trim();
  if (!text || assistantSending.value) return;
  assistantQuestion.value = "";
  assistantMessages.value.push({ role: "user", text });
  assistantMessages.value.push({ role: "assistant", text: "", thinking: true });
  assistantSending.value = true;
  assistantStatus.value = "Thinking...";
  try {
    await streamAssistant({ message: text, threadId: assistantThread.value, onEvent(event) {
      const current = assistantMessages.value.at(-1);
      if (event.event === "token") current.text += event.text || "";
      if (event.event === "status" || event.event === "tool_start") assistantStatus.value = event.text || "Working...";
      if (event.event === "final_answer") current.text = event.text || current.text;
    }});
  } catch (error) { assistantMessages.value.at(-1).text = error.message; }
  finally { assistantMessages.value.at(-1).thinking = false; assistantSending.value = false; assistantStatus.value = ""; }
}

onMounted(async () => { try { await getHealth(); online.value = true; } catch { online.value = false; } });
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand-lockup"><div class="brand-mark">▤</div><div class="brand-copy"><strong>DocuPilot</strong><span>Intelligent Document &amp; Data Processing</span></div></div>
      <div class="topbar-actions"><span :class="['status', { offline: !online }]"><span class="status-dot" />{{ online ? "System Online" : "System Offline" }}</span><span class="workspace-user"><b>D</b><span>DataPilot<br /><small>Workspace</small></span></span></div>
    </header>
    <div class="workspace">
      <nav class="sidebar" aria-label="Main navigation">
        <div class="sidebar-section"><span class="sidebar-label">Workspace</span><button v-for="route in routes.slice(0, 5)" :key="route.id" :class="['nav-item', { active: activeRoute === route.id }]" @click="activeRoute = route.id"><span class="nav-icon">{{ route.icon }}</span><span><strong>{{ route.label }}</strong><small>{{ route.hint }}</small></span></button></div>
        <div class="sidebar-section sidebar-bottom"><button v-for="route in routes.slice(5)" :key="route.id" :class="['nav-item', { active: activeRoute === route.id }]" @click="activeRoute = route.id"><span class="nav-icon">{{ route.icon }}</span><span><strong>{{ route.label }}</strong><small>{{ route.hint }}</small></span></button><div class="sidebar-note"><b>✦ AI-powered workspace</b><span>Analyze, transform, and understand your files in one place.</span></div></div>
      </nav>
      <main class="content">
        <HomeView v-if="activeRoute === 'home'" @navigate="activeRoute = $event === 'document-intelligence' ? 'documents' : $event" />
        <DataAgentView v-else-if="activeRoute === 'data-agent'" />
        <DocumentIntelligenceView v-else-if="activeRoute === 'documents'" />
        <AnalyticsView v-else-if="activeRoute === 'analytics'" />
        <WorkflowView v-else-if="activeRoute === 'workflows'" />
        <SettingsView v-else-if="activeRoute === 'settings'" />
      </main>
    </div>
    <button class="assistant-fab" :class="{ active: assistantOpen }" aria-label="Toggle DataPilot Assistant" @click="assistantOpen = !assistantOpen">✦<span>AI Assistant</span></button>
    <aside v-if="assistantOpen" class="assistant-drawer"><div class="drawer-head"><div><b>✦ DataPilot Assistant</b><small><i /> Online</small></div><button @click="assistantOpen = false">×</button></div><div class="drawer-messages" aria-live="polite"><p v-if="!assistantMessages.length" class="drawer-empty">Ask anything about your active workspace.</p><div v-for="(message, index) in assistantMessages" :key="index" :class="['drawer-message', message.role]"><b>{{ message.role === 'user' ? 'You' : 'Assistant' }}</b><span v-if="message.thinking" class="thinking"><i /><i /><i /> {{ assistantStatus }}</span><p v-else>{{ message.text }}</p></div></div><form class="drawer-form" @submit.prevent="askAssistant"><input v-model="assistantQuestion" placeholder="Ask anything..." :disabled="assistantSending" /><button type="submit" :disabled="assistantSending || !assistantQuestion.trim()">→</button></form></aside>
  </div>
</template>
