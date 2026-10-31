+<script setup>
const emit = defineEmits(["navigate"]);
function go(id) { emit("navigate", id); }

const capabilities = [
  { id: "data-agent", title: "Data Agent", tone: "blue", icon: "#", description: "Ask questions about Excel files in natural language. Get insights, summaries, and answers.", checks: ["Ask questions about your data", "Get summaries and insights", "Explore trends and patterns"] },
  { id: "document-assistant", title: "Document Assistant", tone: "purple", icon: "[]", description: "Ask cited questions about the Nimbus Orchard Technologies Company Handbook.", checks: ["Explore handbook policies and company information", "Answers cite source pages and sections", "Pre-loaded knowledge base, no uploads needed"] },
  { id: "document-intelligence", title: "Document Intelligence", tone: "green", icon: "=", description: "Classify documents and extract structured data with field-level confidence and review flags.", checks: ["Document classification", "Extract key fields", "Review uncertain handwriting"] },
];
</script>

<template>
  <section class="home-view">
    <div class="hero">
      <div class="hero-copy">
        <p class="eyebrow">AI-Powered</p>
        <h1>Welcome to<br /><span>DocuPilot!</span></h1>
        <p class="hero-description">An intelligent document and data processing platform that helps you extract insights, chat with documents, and classify information from complex files - all in one place.</p>
      </div>
      <div class="hero-visual" aria-hidden="true">
        <span class="floating-label understand">[+] &nbsp; Understand Documents</span>
        <div class="document-stack"><div class="document-sheet back"></div><div class="document-sheet front"><i></i><i></i><i></i><i></i></div></div>
        <span class="floating-label extract">[#] &nbsp; Extract Structured Data</span>
        <span class="floating-label ask">[?] &nbsp; Ask Questions</span>
      </div>
    </div>
    <div class="capability-heading"><h2>Explore Our Capabilities</h2><p>Choose a module to get started. Each module supports a different part of your document and data journey.</p></div>
    <div class="capability-grid">
      <article v-for="capability in capabilities" :key="capability.id" :class="['capability-card', capability.tone]">
        <div class="capability-title"><span class="capability-icon">{{ capability.icon }}</span><h3>{{ capability.title }}</h3></div>
        <p>{{ capability.description }}</p>
        <ul><li v-for="check in capability.checks" :key="check">&#10003; &nbsp;{{ check }}</li></ul>
        <button class="capability-action" @click="go(capability.id)">Go to {{ capability.title }} <span>-&gt;</span></button>
      </article>
    </div>
  </section>
</template>
