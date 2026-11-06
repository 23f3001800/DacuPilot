async function readError(response) {
  try {
    const payload = await response.json();
    if (typeof payload.detail === "string") return payload.detail;
    if (Array.isArray(payload.detail))
      return payload.detail.map((item) => item.msg).join("; ");
    return payload.message || "Request failed (" + response.status + ").";
  } catch {
    return "Request failed (" + response.status + ").";
  }
}

async function request(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

function jsonPost(path, payload, options = {}) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    ...options,
  });
}

export async function readEventStream(
  response,
  onEvent,
  { requireDone = true } = {},
) {
  if (!response.ok || !response.body)
    throw new Error(await readError(response));
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;
  const dispatch = (frame) => {
    const data = frame
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data) return;
    if (data === "[DONE]") {
      finished = true;
      return;
    }
    let event;
    try {
      event = JSON.parse(data);
    } catch {
      throw new Error(
        "The server sent an unreadable update. Please try again.",
      );
    }
    onEvent(event);
  };
  try {
    while (!finished) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      buffer = buffer.replace(/\r\n/g, "\n");
      const frames = buffer.split("\n\n");
      buffer = frames.pop() || "";
      for (const frame of frames) {
        dispatch(frame);
        if (finished) break;
      }
      if (done) {
        if (!finished && buffer.trim()) dispatch(buffer);
        if (requireDone && !finished)
          throw new Error(
            "The connection ended before the request completed. Please try again.",
          );
        return;
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export const getHealth = (signal) => request("/api/health", { signal });
export const getWorkbookSchema = (threadId) =>
  request("/api/data/schema?thread_id=" + encodeURIComponent(threadId));
export const getWorkbookPreview = (threadId, offset = 0, limit = 50) =>
  request(
    "/api/data/preview?thread_id=" +
      encodeURIComponent(threadId) +
      "&offset=" +
      offset +
      "&limit=" +
      limit,
  );
export const getWorkbookDashboard = (threadId) =>
  request("/api/data/dashboard?thread_id=" + encodeURIComponent(threadId));
export const getGeneratedCharts = (threadId) =>
  request("/api/data/charts?thread_id=" + encodeURIComponent(threadId));
export const getWorkbookHistory = (threadId) =>
  request("/api/data/history?thread_id=" + encodeURIComponent(threadId));
export const getWorkbookDownloadUrl = (threadId) =>
  "/api/data/workbook/download?thread_id=" + encodeURIComponent(threadId);
export const deleteWorkbook = (threadId) =>
  request("/api/data/workbook?thread_id=" + encodeURIComponent(threadId), {
    method: "DELETE",
  });
export const undoWorkbookChange = (threadId) =>
  request("/api/data/history/undo?thread_id=" + encodeURIComponent(threadId), {
    method: "POST",
  });
export const selectWorkbookSheet = (threadId, sheetName) =>
  jsonPost("/api/data/sheets/select", {
    thread_id: threadId,
    sheet_name: sheetName,
  });
export const generateWorkbookChart = (
  threadId,
  column = null,
  categoryColumn = null,
  signal,
) =>
  jsonPost(
    "/api/data/charts/generate",
    { thread_id: threadId, column, category_column: categoryColumn },
    { signal },
  );
export const previewColumnOperation = ({
  threadId,
  columnName,
  formula,
  operation = "add",
}) =>
  jsonPost("/api/data/column/preview", {
    thread_id: threadId,
    column_name: columnName,
    formula,
    operation,
  });
export const applyColumnOperation = ({ threadId, operationId }) =>
  jsonPost("/api/data/column/apply", {
    thread_id: threadId,
    operation_id: operationId,
  });
export const previewCleaningOperation = (threadId, operation) =>
  jsonPost("/api/data/cleaning/preview", { thread_id: threadId, operation });
export const applyCleaningOperation = (threadId, preview) =>
  jsonPost("/api/data/cleaning/apply", {
    thread_id: threadId,
    operation: preview.operation,
    operation_id: preview.operation_id,
  });
export async function uploadWorkbook(file, threadId) {
  const body = new FormData();
  body.set("file", file);
  body.set("thread_id", threadId);
  return request("/api/data/upload", { method: "POST", body });
}

export async function streamAssistant({
  message,
  threadId,
  processingConsent = false,
  signal,
  onEvent,
}) {
  const body = {
    message,
    thread_id: threadId,
    processing_consent: processingConsent === true,
  };
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  return readEventStream(response, onEvent);
}

export async function streamWorkflow({ threadId, onEvent, signal }) {
  const response = await fetch(
    "/api/workflows/run?thread_id=" + encodeURIComponent(threadId),
    { method: "POST", signal },
  );
  return readEventStream(response, onEvent);
}

export async function processDocuments({ files, onEvent, signal }) {
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  body.set("external_processing_consent", "true");
  const response = await fetch("/api/documents/process/stream", {
    method: "POST",
    body,
    signal,
  });
  return readEventStream(response, onEvent, { requireDone: false });
}
