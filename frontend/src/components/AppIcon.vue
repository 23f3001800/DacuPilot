<script setup>
import { computed } from "vue";
const props = defineProps({
  name: { type: String, default: "file" },
  size: { type: [Number, String], default: 18 },
});
const icons = {
  logo: "M5 19V12M12 19V5M19 19V9",
  table: "M3 3h18v18H3zM3 9h18M9 3v18M3 15h18M15 9v12",
  chart: "M4 4v16h17M8 15l4-5 4 2 5-7",
  files: "M14 3H5v15h12V6zM14 3v4h3M9 21h12V8",
  file: "M14 3H5v18h14V8zM14 3v5h5M8 12h8M8 16h6",
  upload: "M12 16V3M7 8l5-5 5 5M4 15v6h16v-6",
  download: "M12 3v13M7 11l5 5 5-5M4 16v5h16v-5",
  refresh:
    "M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1",
  trash: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7",
  settings:
    "M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1zM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  message: "M21 11a8 8 0 0 1-8 8H8l-5 3V11a9 9 0 0 1 18 0M8 10h8M8 14h5",
  close: "M6 6l12 12M18 6 6 18",
  check: "M5 12l4 4L19 6",
  chevron: "m9 5 7 7-7 7",
  down: "m6 9 6 6 6-6",
  send: "M12 20V4M6 10l6-6 6 6",
  arrow: "M4 12h16M14 6l6 6-6 6",
  external: "M14 3h7v7M21 3 10 14M10 3H3v18h18v-7",
  clock: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0M12 7v5l3 2",
  history: "M3 4v6h6M3 10a9 9 0 1 1 2 8M12 7v5l4 2",
  sparkle: "m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z",
  alert: "m12 3 10 18H2zM12 9v5M12 17v.1",
  shield: "M12 3 3 7v6c0 5 9 8 9 8s9-3 9-8V7zM8 12l3 3 5-6",
  play: "m8 4 12 8-12 8z",
  stop: "M6 6h12v12H6z",
  copy: "M8 8h13v13H8zM16 4V2H2v14h2",
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  search: "M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0M15 15l6 6",
  plus: "M12 4v16M4 12h16",
  undo: "M9 4 3 10l6 6M3 10h11a7 7 0 0 1 0 14",
  help: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0M9 9a3 3 0 1 1 5 2c-2 1-2 2-2 3M12 17v.1",
};
const path = computed(() => icons[props.name] || icons.file);
</script>
<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    class="app-icon"
  >
    <path :d="path" />
  </svg>
</template>
