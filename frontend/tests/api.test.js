import test from "node:test";
import assert from "node:assert/strict";
import { readEventStream, streamAssistant } from "../src/api.js";

function streamResponse(text, chunkSize = 7) {
  const bytes = new TextEncoder().encode(text);
  return new Response(
    new ReadableStream({
      start(controller) {
        for (let offset = 0; offset < bytes.length; offset += chunkSize)
          controller.enqueue(bytes.slice(offset, offset + chunkSize));
        controller.close();
      },
    }),
    { headers: { "Content-Type": "text/event-stream" } },
  );
}

test("SSE preserves chunked UTF-8, CRLF boundaries, and completion", async () => {
  const events = [];
  await readEventStream(
    streamResponse(
      'data: {"event":"token","text":"Revenue ₹230"}\r\n\r\ndata: [DONE]\r\n\r\n',
      1,
    ),
    (event) => events.push(event),
  );
  assert.deepEqual(events, [{ event: "token", text: "Revenue ₹230" }]);
});

test("SSE refuses to treat an interrupted answer as complete", async () => {
  await assert.rejects(
    readEventStream(
      streamResponse('data: {"event":"token","text":"Partial answer"}\n\n'),
      () => {},
    ),
    /connection ended before/,
  );
});

test("SSE reports malformed server events", async () => {
  await assert.rejects(
    readEventStream(
      streamResponse("data: {broken}\n\ndata: [DONE]\n\n"),
      () => {},
    ),
    /unreadable update/,
  );
});

test("document processing accepts its explicit complete event without a DONE sentinel", async () => {
  const events = [];
  await readEventStream(
    streamResponse('data: {"type":"complete","result":{"job_id":"test"}}\n\n'),
    (event) => events.push(event),
    { requireDone: false },
  );
  assert.equal(events[0].result.job_id, "test");
});

test("workbook requests send the explicit consent value and cancellation signal", async () => {
  const originalFetch = globalThis.fetch;
  const controller = new AbortController();
  let captured;
  globalThis.fetch = async (path, options) => {
    captured = { path, options };
    return streamResponse("data: [DONE]\n\n");
  };
  try {
    await streamAssistant({
      message: "Total Revenue",
      threadId: "test-workspace",
      processingConsent: true,
      signal: controller.signal,
      onEvent() {},
    });
    assert.equal(captured.path, "/api/chat/stream");
    assert.equal(JSON.parse(captured.options.body).processing_consent, true);
    assert.equal(captured.options.signal, controller.signal);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("company help uses its own API and does not inherit workbook consent", async () => {
  const originalFetch = globalThis.fetch;
  let captured;
  globalThis.fetch = async (path, options) => {
    captured = { path, options };
    return streamResponse("data: [DONE]\n\n");
  };
  try {
    await streamAssistant({
      message: "Company leave policy",
      threadId: "company-thread",
      mode: "document-assistant",
      onEvent() {},
    });
    assert.equal(captured.path, "/api/document-assistant/chat/stream");
    assert.equal(
      Object.hasOwn(JSON.parse(captured.options.body), "processing_consent"),
      false,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("validation errors remain readable to the user", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: [{ msg: "Session is required" }] }), {
      status: 422,
      headers: { "Content-Type": "application/json" },
    });
  try {
    await assert.rejects(
      streamAssistant({ message: "test", threadId: "", onEvent() {} }),
      /Session is required/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
