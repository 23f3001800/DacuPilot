<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
import { clearDocumentSession, streamAssistant } from "../api";
import { formatLatency, readStoredArray } from "../lib/format.js";
import AppIcon from "./AppIcon.vue";
import RichText from "./RichText.vue";
import AnswerMeta from "./AnswerMeta.vue";

defineProps({ online: Boolean });
const open = ref(false);
const threadKey = "insightpilot-company-help-thread";
let storedThread = sessionStorage.getItem(threadKey);
if (!storedThread || !/^[0-9a-f-]{36}$/i.test(storedThread)) {
  storedThread = crypto.randomUUID();
  sessionStorage.setItem(threadKey, storedThread);
}
const threadId = ref(storedThread);
const historyKey = "insightpilot-company-help:" + threadId.value;
const messages = ref(readStoredArray(historyKey, sessionStorage));
const question = ref("");
const sending = ref(false);
const status = ref("");
const elapsed = ref(0);
const list = ref(null);
const input = ref(null);
const notice = ref("");
let controller;
let timer;
let followBottom = true;

function scrollToLatest() {
  if (followBottom && list.value)
    list.value.scrollTop = list.value.scrollHeight;
}
watch(messages, () => nextTick(scrollToLatest), { deep: true, flush: "post" });
watch(open, async (value) => {
  if (value) {
    await nextTick();
    input.value?.focus();
    scrollToLatest();
  }
});

async function clearConversation() {
  if (sending.value) return;
  try {
    await clearDocumentSession(threadId.value);
    messages.value = [];
    sessionStorage.removeItem(historyKey);
    notice.value = "";
  } catch (error) {
    notice.value = error.message;
  }
}

async function ask(value = question.value) {
  const text = value.trim();
  if (!text || sending.value) return;
  question.value = "";
  followBottom = true;
  messages.value.push({ id: crypto.randomUUID(), role: "user", text });
  const index =
    messages.value.push({
      id: crypto.randomUUID(),
      role: "assistant",
      text: "",
      thinking: true,
      confidence: null,
      citations: [],
      latencyMs: null,
      rationale: "",
    }) - 1;
  const answer = messages.value[index];
  sending.value = true;
  status.value = "Thinking";
  notice.value = "";
  const started = performance.now();
  elapsed.value = 0;
  controller = new AbortController();
  timer = setInterval(() => {
    elapsed.value = Math.round(performance.now() - started);
  }, 100);
  try {
    await streamAssistant({
      message: text,
      threadId: threadId.value,
      mode: "document-assistant",
      signal: controller.signal,
      onEvent(event) {
        if (event.event === "token") answer.text += event.text || "";
        if (event.event === "final_answer")
          answer.text = event.text || answer.text;
        if (event.event === "status") status.value = event.text || "Thinking";
        if (event.event === "evaluation") {
          const metrics = event.payload || {};
          answer.confidence =
            event.confidence_score ?? metrics.confidence_score ?? null;
          answer.citations = (metrics.sources || []).map((source) =>
            typeof source === "string" ? { source } : source,
          );
          answer.rationale = metrics.evaluation_rationale || "";
        }
        if (event.event === "error") {
          answer.error = true;
          answer.text =
            event.details ||
            event.message ||
            "Company help could not answer. Try again.";
        }
      },
    });
    if (!answer.text.trim()) {
      answer.error = true;
      answer.text = "The server returned no answer. Please try again.";
    }
  } catch (error) {
    answer.error = error.name !== "AbortError";
    if (error.name === "AbortError") {
      answer.text ||= "Response stopped.";
      answer.confidence = null;
    } else answer.text = error.message;
  } finally {
    clearInterval(timer);
    answer.latencyMs = Math.round(performance.now() - started);
    answer.thinking = false;
    sending.value = false;
    status.value = "";
    try {
      sessionStorage.setItem(
        historyKey,
        JSON.stringify(messages.value.slice(-40)),
      );
    } catch {
      notice.value =
        "This browser could not keep the conversation after a refresh.";
    }
    await nextTick();
    input.value?.focus();
  }
}
function handleEnter(event) {
  if (!event.shiftKey && !event.isComposing) {
    event.preventDefault();
    ask();
  }
}
onBeforeUnmount(() => {
  controller?.abort();
  clearInterval(timer);
});
</script>

<template>
  <button
    class="help-launcher"
    :class="{ active: open }"
    :aria-expanded="open"
    aria-controls="company-help"
    :aria-label="open ? 'Close company help' : 'Open company help'"
    :title="open ? 'Close company help' : 'Company help'"
    @click="open = !open"
  >
    <AppIcon :name="open ? 'close' : 'message'" :size="22" />
  </button>
  <aside
    v-show="open"
    id="company-help"
    class="help-panel"
    role="dialog"
    aria-labelledby="company-help-title"
  >
    <header class="help-header">
      <span class="icon-tile small"><AppIcon name="message" /></span>
      <div>
        <h2 id="company-help-title">Company help</h2>
        <p>
          {{
            online
              ? "General questions & company documents"
              : "Backend connection unavailable"
          }}
        </p>
      </div>
      <button
        class="icon-button"
        :disabled="sending || !messages.length"
        title="Clear conversation"
        aria-label="Clear company help conversation"
        @click="clearConversation"
      >
        <AppIcon name="trash" :size="16" /></button
      ><button
        class="icon-button"
        aria-label="Close company help"
        @click="open = false"
      >
        <AppIcon name="close" />
      </button>
    </header>
    <div
      ref="list"
      class="help-messages"
      role="log"
      aria-label="Company help conversation"
      aria-live="polite"
      @scroll="
        followBottom =
          $event.target.scrollHeight -
            $event.target.scrollTop -
            $event.target.clientHeight <
          100
      "
    >
      <div v-if="!messages.length" class="help-welcome">
        <span class="icon-tile"><AppIcon name="shield" :size="24" /></span>
        <h3>How can I help?</h3>
        <p>
          Ask a general question or find an answer in the company handbook and
          approved policies.
        </p>
        <button
          class="suggestion"
          @click="ask('What is the company leave policy?')"
        >
          Company leave policy<AppIcon name="arrow" :size="15" /></button
        ><button
          class="suggestion"
          @click="ask('Where can I find company support contacts?')"
        >
          Support contacts<AppIcon name="arrow" :size="15" />
        </button>
      </div>
      <article
        v-for="message in messages"
        :key="message.id"
        class="conversation-message"
        :class="[message.role, { failed: message.error }]"
      >
        <div class="message-author">
          {{ message.role === "user" ? "You" : "Document Assistant" }}
        </div>
        <RichText v-if="message.text" :text="message.text" />
        <div v-if="message.thinking" class="thinking-line" role="status">
          <span class="thinking-dots"><i /><i /><i /></span
          ><span>{{ status }}</span
          ><b class="latency">{{ formatLatency(elapsed) }}</b>
        </div>
        <AnswerMeta
          v-if="message.role === 'assistant' && !message.thinking"
          :confidence="message.confidence"
          :latency-ms="message.latencyMs"
          :citations="message.citations"
          :rationale="message.rationale"
        />
      </article>
    </div>
    <p v-if="notice" class="inline-notice">{{ notice }}</p>
    <form class="help-composer" @submit.prevent="ask()">
      <label class="sr-only" for="company-question">Ask Company Help</label
      ><textarea
        id="company-question"
        ref="input"
        v-model="question"
        rows="2"
        maxlength="8000"
        placeholder="Ask a general or company question…"
        :disabled="sending"
        @keydown.enter="handleEnter"
      /><button
        v-if="sending"
        type="button"
        class="send-button"
        aria-label="Stop company help response"
        @click="controller?.abort()"
      >
        <AppIcon name="stop" :size="17" /></button
      ><button
        v-else
        class="send-button"
        :disabled="!question.trim()"
        aria-label="Send company help question"
      >
        <AppIcon name="send" :size="19" />
      </button>
    </form>
  </aside>
</template>
