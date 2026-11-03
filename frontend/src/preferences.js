import { reactive } from "vue";

const defaults = { liveUpdates: true, citations: true, compactTables: false };
export const preferences = reactive({ ...defaults });

export function loadPreferences() {
  try {
    Object.assign(preferences, defaults, JSON.parse(localStorage.getItem("datapilot-settings") || "{}"));
  } catch {
    Object.assign(preferences, defaults);
  }
}

export function savePreferences() {
  localStorage.setItem("datapilot-settings", JSON.stringify({ ...preferences }));
}
