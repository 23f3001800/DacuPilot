export function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString() : "—";
}
export function formatLatency(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number)
    ? Math.round(number).toLocaleString() + " ms"
    : null;
}
export function formatConfidence(value) {
  if (value === null || value === undefined || value === "")
    return "Not scored";
  const number = Number(value);
  return Number.isFinite(number)
    ? Math.round(number <= 1 ? number * 100 : number) + "%"
    : "Not scored";
}
export function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date unavailable"
    : date.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}
export function readStoredArray(key, storage = localStorage) {
  try {
    const value = JSON.parse(storage.getItem(key) || "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}
export function downloadJson(value, filename) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
