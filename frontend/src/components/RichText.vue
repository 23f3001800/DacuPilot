<script setup>
import { computed } from "vue";
import { renderMarkdown } from "../lib/markdown.js";
const props = defineProps({ text: { type: String, default: "" } });
const html = computed(() => renderMarkdown(props.text));
</script>
<template><div class="rich-text" v-html="html" /></template>
