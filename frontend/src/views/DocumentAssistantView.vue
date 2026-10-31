<script setup>
import { onMounted, ref } from "vue";
import { streamAssistant } from "../api";

const question = ref("");
const sending = ref(false);
const status = ref("");
const messages = ref([]);
const threadId = ref(sessionStorage.getItem("datapilot-doc-thread-id") || crypto.randomUUID());
const prompts = [
  "What happens when confidence is low?",
  "What is the privacy policy for user data?",
  "How should uncertain document fields be reviewed?",
];

async function ask(text = question.value) {
  const message = text.trim();
  if (!message || sending.value) return;
  question.value = "";
  messages.value.push({ role: "user", text: message });
  messages.value.push({ role: "assistant", text: "" });
  sending.value = true;
  status.value = "Searching handbook...";
  try {
    await streamAssistant({
      message,
      threadId: threadId.value,
      mode: "document-assistant",
      onEvent(event) {
        if (event.event === "status") status.value = event.text || "";
        if (event.event === "token") messages.value.at(-1).text += event.text || "";
        if (event.event === "final_answer") messages.value.at(-1).text = event.text || messages.value.at(-1).text;
      },
    });
  } catch (error) {
    messages.value.at(-1).text = error.message;
  } finally {
    sending.value = false;
    status.value = "";
  }
}

onMounted(() => {
  messages.value.push({
    role: "assistant",
    text: "Ask me about the company handbook, application policies, or document-review guidance.",
  });
});
</script>

<template>
  <section class="workflow-view">
    <div class="view-heading">
      <div>
        <p class="eyebrow">Grounded document chat</p>
        <h1>Document Assistant</h1>
        <p>Ask questions about the preloaded handbook and receive streamed, source-grounded answers.</p>
      </div>
      <span v-if="status" class="status-pill">{{ status }}</span>
    </div>
    <section class="panel chat-panel">
      <div class="prompt-row">
        <button v-for="prompt in prompts" :key="prompt" class="prompt-button" @click="ask(prompt)">{{ prompt }}</button>
      </div>
      <div class="message-list" aria-live="polite">
        <div v-for="(message, index) in messages" :key="index" :class="['message', message.role]">
          <strong>{{ message.role === "user" ? "You" : "Document Assistant" }}</strong>
          <p>{{ message.text }}</p>
        </div>
      </div>
      <form class="question-form" @submit.prevent="ask()">
        <input v-model="question" placeholder="Ask about the handbook..." :disabled="sending" />
        <button class="primary-button" type="submit" :disabled="sending || !question.trim()">Send</button>
      </form>
    </section>
  </section>
</template>
