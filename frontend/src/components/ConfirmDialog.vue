<script setup>
import { nextTick, ref, watch } from "vue";
import AppIcon from "./AppIcon.vue";
const props = defineProps({
  open: Boolean,
  busy: Boolean,
  title: String,
  message: String,
  confirmLabel: { type: String, default: "Confirm" },
});
const emit = defineEmits(["cancel", "confirm"]);
const dialog = ref(null);
watch(
  () => props.open,
  async (open) => {
    await nextTick();
    if (open && dialog.value && !dialog.value.open) dialog.value.showModal();
    if (!open && dialog.value?.open) dialog.value.close();
  },
  { immediate: true },
);
</script>
<template>
  <dialog
    ref="dialog"
    class="confirm-dialog"
    aria-labelledby="confirm-dialog-title"
    @cancel.prevent="!busy && emit('cancel')"
  >
    <div class="dialog-content">
      <span class="dialog-icon"><AppIcon name="trash" :size="23" /></span>
      <h2 id="confirm-dialog-title">{{ title }}</h2>
      <p>{{ message }}</p>
      <div class="dialog-actions">
        <button
          class="button secondary"
          autofocus
          :disabled="busy"
          @click="emit('cancel')"
        >
          Cancel</button
        ><button
          class="button danger"
          :disabled="busy"
          @click="emit('confirm')"
        >
          {{ busy ? "Deleting…" : confirmLabel }}
        </button>
      </div>
    </div>
  </dialog>
</template>
