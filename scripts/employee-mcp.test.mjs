import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const adapter = fileURLToPath(new URL('./employee-mcp.mjs', import.meta.url));

function run(url, input) {
  const child = spawn(process.execPath, [adapter], {
    env: {
      ...process.env,
      EMPLOYEE_MCP_URL: url,
      EMPLOYEE_MCP_EMAIL: 'hr@example.test',
      EMPLOYEE_MCP_PASSWORD: 'test-private-password',
    },
  });
  let stdout = '';
  let stderr = '';
  child.stdout.on('data', (chunk) => {
    stdout += chunk;
  });
  child.stderr.on('data', (chunk) => {
    stderr += chunk;
  });
  child.stdin.end(input);
  return once(child, 'close').then(([code]) => ({ code, stdout, stderr }));
}

test('STDIO adapter authenticates, refreshes CSRF and forwards MCP without logging credentials', async () => {
  const seen = [];
  const server = createServer(async (req, res) => {
    let body = '';
    for await (const chunk of req) body += chunk;
    res.setHeader('Content-Type', 'application/json');
    if (req.url === '/api/auth/csrf') {
      res.setHeader('Set-Cookie', 'XSRF-TOKEN=test-csrf; Path=/');
      res.end('{}');
    } else if (req.url === '/api/auth/login') {
      assert.equal(req.headers['x-xsrf-token'], 'test-csrf');
      assert.equal(JSON.parse(body).password, 'test-private-password');
      res.setHeader('Set-Cookie', 'JSESSIONID=test-session; Path=/; HttpOnly');
      res.end('{}');
    } else {
      assert.equal(req.url, '/api/mcp/employees');
      assert.match(req.headers.cookie, /JSESSIONID=test-session/);
      assert.equal(req.headers['x-xsrf-token'], 'test-csrf');
      const message = JSON.parse(body);
      seen.push(message.method);
      if (!Object.hasOwn(message, 'id')) {
        res.writeHead(202).end();
      } else {
        if (message.method === 'tools/call')
          assert.equal(req.headers['mcp-protocol-version'], '2025-11-25');
        res.end(
          JSON.stringify({
            jsonrpc: '2.0',
            id: message.id,
            result:
              message.method === 'initialize' ? { protocolVersion: '2025-11-25' } : { total: 42 },
          }),
        );
      }
    }
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  try {
    const result = await run(
      `http://127.0.0.1:${server.address().port}`,
      [
        { jsonrpc: '2.0', id: 1, method: 'initialize', params: {} },
        { jsonrpc: '2.0', method: 'notifications/initialized' },
        {
          jsonrpc: '2.0',
          id: 2,
          method: 'tools/call',
          params: { name: 'count_employees', arguments: {} },
        },
      ]
        .map(JSON.stringify)
        .join('\n'),
    );
    assert.equal(result.code, 0);
    assert.equal(result.stderr, '');
    const replies = result.stdout.trim().split('\n').map(JSON.parse);
    assert.equal(replies.length, 2);
    assert.equal(replies[1].result.total, 42);
    assert.deepEqual(seen, ['initialize', 'notifications/initialized', 'tools/call']);
    assert(!result.stdout.includes('test-private-password'));
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('STDIO adapter rejects nonlocal plaintext URLs without exposing credentials', async () => {
  const result = await run('http://example.test', '');
  assert.equal(result.code, 1);
  assert.equal(result.stdout, '');
  assert.match(result.stderr, /EMPLOYEE_MCP_URL/);
  assert(!result.stderr.includes('test-private-password'));
});
