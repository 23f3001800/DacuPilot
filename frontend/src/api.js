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

export async function getWorkbookSchema(threadId = "default") {
  const response = await fetch(`/api/data/schema?thread_id=${encodeURIComponent(threadId)}`);
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function uploadWorkbook(file, threadId = "default") {
  const body = new FormData();
  body.set("file", file);
  body.set("thread_id", threadId);
  const response = await fetch("/api/data/upload", { method: "POST", body });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function getWorkbookPreview(threadId = "default") {
  const response = await fetch(`/api/data/preview?thread_id=${encodeURIComponent(threadId)}`);
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function getWorkbookDashboard(threadId = "default") {
  const response = await fetch(`/api/data/dashboard?thread_id=${encodeURIComponent(threadId)}`);
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function previewColumnOperation({ threadId, columnName, formula }) {
  const response = await fetch("/api/data/column/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, column_name: columnName, formula }),
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

export async function streamAssistant({ message, threadId, mode = "data-agent", onEvent }) {
  const endpoint = mode === "document-assistant"
    ? "/api/document-assistant/chat/stream"
    : "/api/chat/stream";
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, thread_id: threadId }),
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
      try { onEvent(JSON.parse(payload)); } catch { /* Ignore malformed SSE frames. */ }
    }
    if (done) return;
  }
}
