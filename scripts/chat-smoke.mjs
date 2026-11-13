// Exercises the real Java -> Python advisor using anonymous session and CSRF cookies.
import assert from 'node:assert/strict';
import { readChatEvents } from '../FE/src/app/core/chat-stream.ts';

const base = process.argv[2] || 'http://127.0.0.1:8080';
const requireLlm = process.argv.includes('--require-llm');
const cookies = new Map();

function remember(response) {
  for (const value of response.headers.getSetCookie()) {
    const [pair] = value.split(';');
    const separator = pair.indexOf('=');
    cookies.set(pair.slice(0, separator), pair.slice(separator + 1));
  }
}

async function ask(message, courseSlug = null, isolated = false, topic = 'courses') {
  if (isolated) cookies.clear();
  const csrf = await fetch(new URL('/api/auth/csrf', base), {
    headers: { Cookie: [...cookies].map(([key, value]) => `${key}=${value}`).join('; ') },
  });
  assert.equal(csrf.status, 200);
  remember(csrf);
  const response = await fetch(new URL('/api/chat/messages', base), {
    method: 'POST',
    headers: {
      Cookie: [...cookies].map(([key, value]) => `${key}=${value}`).join('; '),
      'X-XSRF-TOKEN': decodeURIComponent(cookies.get('XSRF-TOKEN') || ''),
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({ message, courseSlug, topic }),
  });
  remember(response);
  if (response.status !== 200) assert.fail(await response.text());
  const events = new Map();
  const deltas = [];
  const started = performance.now();
  let firstDeltaMs = null;
  let finalAnswerMs = null;
  for await (const event of readChatEvents(response.body)) {
    events.set(event.event, event.data);
    if (event.event === 'answer_delta') {
      firstDeltaMs ??= performance.now() - started;
      deltas.push(event.data.text);
    }
    if (event.event === 'answer') finalAnswerMs = performance.now() - started;
    if (event.event === 'done') break;
  }
  assert(!events.has('error'), JSON.stringify(events.get('error')));
  assert(events.has('done'), 'Missing completion event');
  assert(events.has('answer'), 'Missing authoritative answer');
  events.set('stream_stats', { deltas, firstDeltaMs, finalAnswerMs });
  return events;
}

let events = await ask('Mình mới bắt đầu học lập trình, ngân sách dưới 500 nghìn');
assert.deepEqual(
  events.get('courses').map((course) => course.slug),
  ['python-co-ban'],
);
assert.equal(Number(events.get('courses')[0].price), 399000);
assert.equal(events.get('courses')[0].enrolled, false);

events = await ask('Còn Figma thì sao');
assert.equal(events.get('courses')[0].slug, 'ui-ux-figma');
assert(events.get('courses').every((course) => Number(course.price) < 500000));

events = await ask('Mở khóa học này', 'java-spring-boot', true);
assert.equal(events.get('courses')[0].slug, 'java-spring-boot');
assert.equal(events.get('courses')[0].enrolled, false);
events = await ask('Có hoàn tiền không');
assert.equal(events.get('courses').length, 0);

events = await ask('Threat Hunting là gì?', null, false, 'secops');
assert.match(events.get('answer').text, /truy vấn|SQL|events/i);
assert.equal(events.get('courses').length, 0);
assert.match(
  events.get('sources')[0].url,
  /^https:\/\/docs\.cmctelecom\.io\/vi\/secops\/threat-hunting\/overview#/,
);
assert.equal(events.get('done').intent, 'documentation');
assert(['generated', 'extractive'].includes(events.get('done').answerMode));
if (requireLlm) {
  assert.equal(events.get('done').answerMode, 'generated');
  assert.equal(events.get('done').engine, 'secops-bm25+ollama/qwen3:0.6b');
  const stats = events.get('stream_stats');
  assert(stats.deltas.length >= 2, 'Expected multiple live answer deltas');
  assert(
    stats.firstDeltaMs < stats.finalAnswerMs,
    'First delta must arrive before the final answer',
  );
  assert.equal(stats.deltas.join('').trim(), events.get('answer').text);
  console.log(
    `Live stream: ${stats.deltas.length} deltas; first at ${Math.round(stats.firstDeltaMs)} ms, final at ${Math.round(stats.finalAnswerMs)} ms.`,
  );
}

events = await ask('Các bảng dữ liệu gồm những gì?', null, false, 'secops');
assert.match(events.get('answer').text, /events/);
assert.match(events.get('answer').text, /entities/);

events = await ask('Threat Hunting hỗ trợ Kafka KRaft không?', null, false, 'secops');
assert.match(events.get('answer').text, /chưa tìm thấy/);
assert.deepEqual(events.get('sources'), []);

const unauthorized = await fetch(new URL('/api/learning/java-spring-boot/lessons/10', base));
assert.equal(unauthorized.status, 401);
const missingCsrf = await fetch(new URL('/api/chat/messages', base), {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ message: 'Python' }),
});
assert.equal(missingCsrf.status, 403);
console.log(
  'PASS: real Java/Python SSE, course filters/actions, SecOps answers/citations/follow-up/no-match, anonymous CSRF and learning permissions.',
);
