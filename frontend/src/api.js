async function readError(response) {
  try {
    const payload = await response.json();
    return payload.detail || `Request failed (${response.status}).`;
  } catch {
    return `Request failed (${response.status}).`;
  }
}

export async function getHealth() {
  const response = await fetch("/api/health");
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function getWorkbookSchema(threadId) {
  const response = await fetch(`/api/data/schema?thread_id=${encodeURIComponent(threadId)}`);
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function selectWorkbookSheet(threadId, sheetName) {
  const response = await fetch("/api/data/sheets/select", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, sheet_name: sheetName }),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function uploadWorkbook(file, threadId) {
  const body = new FormData();
  body.set("file", file);
  body.set("thread_id", threadId);
  const response = await fetch("/api/data/upload", { method: "POST", body });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function getWorkbookPreview(threadId, offset = 0, limit = 50) {
  const response = await fetch(`/api/data/preview?thread_id=${encodeURIComponent(threadId)}&offset=${offset}&limit=${limit}`);
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function getWorkbookDashboard(threadId) {
  const response = await fetch(`/api/data/dashboard?thread_id=${encodeURIComponent(threadId)}`);
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function generateWorkbookChart(threadId, column = null, categoryColumn = null) {
  const response = await fetch("/api/data/charts/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ thread_id: threadId, column, category_column: categoryColumn }) });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function getGeneratedCharts(threadId) {
  const response = await fetch(`/api/data/charts?thread_id=${encodeURIComponent(threadId)}`);
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export function getWorkbookDownloadUrl(threadId) {
  return `/api/data/workbook/download?thread_id=${encodeURIComponent(threadId)}`;
}

export async function deleteWorkbook(threadId) {
  const response = await fetch(`/api/data/workbook?thread_id=${encodeURIComponent(threadId)}`, { method: "DELETE" });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function previewColumnOperation({ threadId, columnName, formula, operation = "add" }) {
  const response = await fetch("/api/data/column/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, column_name: columnName, formula, operation }),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function applyColumnOperation({ threadId, operationId }) {
  const response = await fetch("/api/data/column/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, operation_id: operationId }),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function streamAssistant({ message, threadId, mode = "data-agent", processingConsent = false, onEvent }) {
  const endpoint = mode === "document-assistant"
    ? "/api/document-assistant/chat/stream"
    : "/api/chat/stream";
  const body = { message, thread_id: threadId };
  if (mode !== "document-assistant") body.processing_consent = processingConsent === true;
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) throw new Error(await readError(response));

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    buffer = buffer.replace(/\r\n/g, "\n");
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";
    for (const raw of events) {
      const line = raw.split("\n").find((item) => item.startsWith("data: "));
      if (!line) continue;
      const payload = line.slice(6);
      if (payload === "[DONE]") return;
      let event;
      try { event = JSON.parse(payload); } catch { continue; }
      onEvent(event);
    }
    if (done) return;
  }
}

export async function streamWorkflow({ threadId, onEvent }) {
  const response = await fetch(`/api/workflows/run?thread_id=${encodeURIComponent(threadId)}`, { method: "POST" });
  if (!response.ok || !response.body) throw new Error(await readError(response));
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    buffer = buffer.replace(/\r\n/g, "\n");
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";
    for (const raw of events) {
      const line = raw.split("\n").find((item) => item.startsWith("data: "));
      if (!line) continue;
      const payload = line.slice(6);
      if (payload === "[DONE]") return;
      let event;
      try { event = JSON.parse(payload); } catch { continue; }
      onEvent(event);
    }
    if (done) return;
  }
}
