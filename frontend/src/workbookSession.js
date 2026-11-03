const SESSION_KEY = "datapilot-thread-id";
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function getWorkbookThreadId() {
  let threadId = sessionStorage.getItem(SESSION_KEY);
  if (!threadId || !UUID_V4.test(threadId)) {
    threadId = crypto.randomUUID();
    sessionStorage.setItem(SESSION_KEY, threadId);
  }
  return threadId;
}

export function getWorkspaceStorageKey(prefix, threadId = getWorkbookThreadId()) {
  return `${prefix}:${threadId}`;
}
