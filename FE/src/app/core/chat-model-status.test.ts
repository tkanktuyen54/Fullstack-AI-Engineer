import assert from 'node:assert/strict';
import { test } from 'node:test';
import { answerModelLabel, modelFailureMessage } from './chat-model-status.ts';

test('A Groq selection is not presented as a successful Groq answer during fallback', () => {
  assert.equal(
    answerModelLabel({
      answerMode: 'extractive',
      modelLabel: 'Groq · old-model',
      engine: 'secops-bm25',
    }),
    'Dữ liệu truy xuất',
  );
  assert.equal(
    answerModelLabel({ answerMode: 'generated', engine: 'secops-bm25+groq/openai/gpt-oss-20b' }),
    'Groq · openai/gpt-oss-20b',
  );
  assert.equal(
    answerModelLabel({ answerMode: 'generated', engine: 'secops-bm25+ollama/qwen3:0.6b' }),
    'Local · qwen3:0.6b',
  );
  assert.equal(answerModelLabel({ modelLabel: 'Groq · model' }), 'Đang xử lý · Groq · model');
});

test('Provider errors have actionable messages and unknown codes are never echoed', () => {
  assert.match(modelFailureMessage('groq_model_decommissioned'), /ngừng hỗ trợ/);
  assert.match(modelFailureMessage('groq_authentication'), /401/);
  assert.match(modelFailureMessage('groq_rate_limited'), /429/);
  assert.match(modelFailureMessage('invalid_generation'), /đã phản hồi/);
  assert(!modelFailureMessage('private-upstream-content').includes('private-upstream-content'));
});

test('Employee tool results show the database tool rather than a selected model', () => {
  assert.equal(
    answerModelLabel({ answerMode: 'tool', engine: 'employee-mcp', modelLabel: 'Groq · model' }),
    'MCP · Nhân sự',
  );
});
