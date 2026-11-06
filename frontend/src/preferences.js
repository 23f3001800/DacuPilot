import { reactive } from "vue";

const defaults = { liveUpdates: true, citations: true, compactTables: false };
export const preferences = reactive({ ...defaults });

export function loadPreferences() {
  try {
    const saved = JSON.parse(
      localStorage.getItem("datapilot-settings") || "{}",
    );
    for (const key of Object.keys(defaults))
      preferences[key] =
        typeof saved?.[key] === "boolean" ? saved[key] : defaults[key];
  } catch {
    Object.assign(preferences, defaults);
  }
}

export function savePreferences() {
  localStorage.setItem(
    "datapilot-settings",
    JSON.stringify(
      Object.fromEntries(
        Object.keys(defaults).map((key) => [key, Boolean(preferences[key])]),
      ),
    ),
  );
}
