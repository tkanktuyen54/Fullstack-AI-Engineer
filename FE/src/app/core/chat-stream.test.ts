import assert from 'node:assert/strict';
import { test } from 'node:test';
import { applyAnswerEvent, readChatEvents } from './chat-stream.ts';

test('Answer deltas accumulate and final answer replaces a rejected draft', () => {
  let state = { text: '', streaming: false };
  state = applyAnswerEvent(state, {
    event: 'answer_delta',
    data: { text: 'Threat ' },
  }) as typeof state;
  state = applyAnswerEvent(state, {
    event: 'answer_delta',
    data: { text: 'Hunting' },
  }) as typeof state;
  assert.equal(state.text, 'Threat Hunting');
  assert.equal(state.streaming, true);
  state = applyAnswerEvent(state, {
    event: 'answer',
    data: { text: 'Trích đoạn đã kiểm tra.' },
  }) as typeof state;
  assert.deepEqual(state, { text: 'Trích đoạn đã kiểm tra.', streaming: false });
});

test('SSE yields a delta while the connection is still open', { timeout: 1000 }, async () => {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(value) {
      controller = value;
    },
  });
  const events = readChatEvents(body);
  controller.enqueue(
    new TextEncoder().encode('event:answer_delta\ndata:{"text":"Tiếng Việt"}\n\n'),
  );
  assert.deepEqual((await events.next()).value, {
    event: 'answer_delta',
    data: { text: 'Tiếng Việt' },
  });
  controller.enqueue(new TextEncoder().encode('event:done\ndata:{}\n\n'));
  controller.close();
  assert.equal((await events.next()).value.event, 'done');
  assert.equal((await events.next()).done, true);
});

test('SSE handles UTF-8 and CRLF split at every byte', async () => {
  const bytes = new TextEncoder().encode(
    'event:answer\r\ndata:{"text":"Khóa học tiếng Việt"}\r\n\r\nevent:done\r\ndata:{}\r\n\r\n',
  );
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
      controller.close();
    },
  });
  const events = [];
  for await (const event of readChatEvents(body)) events.push(event);
  assert.deepEqual(events, [
    { event: 'answer', data: { text: 'Khóa học tiếng Việt' } },
    { event: 'done', data: {} },
  ]);
});

test('SSE ignores comments and supports multiline data in one chunk', async () => {
  const response = new Response(
    ':heartbeat\n\nevent:answer\ndata:{\ndata: "text": "Xin chào"\ndata:}\n\n',
  );
  const events = [];
  for await (const event of readChatEvents(response.body!)) events.push(event);
  assert.deepEqual(events, [{ event: 'answer', data: { text: 'Xin chào' } }]);
});

test('Malformed JSON closes the stream instead of leaving its reader locked', async () => {
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('event:answer\ndata:invalid\n\n'));
    },
    cancel() {
      cancelled = true;
    },
  });
  await assert.rejects(async () => {
    for await (const event of readChatEvents(body)) void event;
  }, SyntaxError);
  assert.equal(cancelled, true);
  assert.equal(body.locked, false);
});
