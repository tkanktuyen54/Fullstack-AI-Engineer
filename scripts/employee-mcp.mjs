import { createInterface } from 'node:readline';

// STDIO adapter for the authenticated Streamable HTTP server in BE.
// stdout is reserved for MCP JSON-RPC; credentials are never included in errors.
class PublicError extends Error {}

async function main() {
  const base = new URL(process.env.EMPLOYEE_MCP_URL || 'http://127.0.0.1:8081');
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(base.hostname);
  if (
    base.username ||
    base.password ||
    base.search ||
    base.hash ||
    base.pathname !== '/' ||
    (base.protocol !== 'https:' && !(local && base.protocol === 'http:'))
  )
    throw new PublicError(
      'EMPLOYEE_MCP_URL phải là HTTPS hoặc HTTP localhost, không có path hay thông tin đăng nhập.',
    );

  const email = process.env.EMPLOYEE_MCP_EMAIL;
  const password = process.env.EMPLOYEE_MCP_PASSWORD;
  if (!email || !password)
    throw new PublicError(
      'Cần đặt EMPLOYEE_MCP_EMAIL và EMPLOYEE_MCP_PASSWORD của tài khoản có quyền nhân sự.',
    );
  const cookies = new Map();
  let protocolVersion;

  async function request(path, body) {
    const headers = { Accept: 'application/json, text/event-stream' };
    if (cookies.size)
      headers.Cookie = [...cookies].map(([key, value]) => `${key}=${value}`).join('; ');
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      if (cookies.has('XSRF-TOKEN'))
        headers['X-XSRF-TOKEN'] = decodeURIComponent(cookies.get('XSRF-TOKEN'));
      if (protocolVersion) headers['MCP-Protocol-Version'] = protocolVersion;
    }
    const response = await fetch(new URL(path, base), {
      method: body === undefined ? 'GET' : 'POST',
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      redirect: 'manual',
      signal: AbortSignal.timeout(15_000),
    });
    for (const cookie of response.headers.getSetCookie()) {
      const pair = cookie.split(';', 1)[0];
      const split = pair.indexOf('=');
      if (split < 1) continue;
      const name = pair.slice(0, split);
      const value = pair.slice(split + 1);
      if (value) cookies.set(name, value);
      else cookies.delete(name);
    }
    return response;
  }

  const before = await request('/api/auth/csrf');
  await before.body?.cancel();
  if (!before.ok) throw new PublicError('Không lấy được phiên CSRF từ backend.');
  const login = await request('/api/auth/login', { email, password });
  await login.body?.cancel();
  if (!login.ok) throw new PublicError('Đăng nhập MCP thất bại. Hãy kiểm tra tài khoản.');
  const after = await request('/api/auth/csrf');
  await after.body?.cancel();
  if (!after.ok) throw new PublicError('Không cập nhật được phiên CSRF sau đăng nhập.');

  const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of lines) {
    if (!line.trim()) continue;
    let message;
    try {
      if (Buffer.byteLength(line) > 16_384) throw new Error();
      message = JSON.parse(line);
      if (message === null || typeof message !== 'object' || Array.isArray(message))
        throw new Error();
    } catch {
      send({
        jsonrpc: '2.0',
        id: null,
        error: { code: -32700, message: 'Yêu cầu MCP không hợp lệ hoặc quá lớn.' },
      });
      continue;
    }
    try {
      const response = await request('/api/mcp/employees', message);
      if (!response.ok) {
        await response.body?.cancel();
        throw new PublicError(
          response.status === 401
            ? 'Phiên đăng nhập đã hết hạn. Hãy khởi động lại MCP.'
            : response.status === 403
              ? 'MCP yêu cầu quyền HR, HR_APPROVER hoặc ADMIN và cấu hình Host/Origin hợp lệ.'
              : 'Backend chưa xử lý được yêu cầu MCP.',
        );
      }
      if (response.status === 202 || response.status === 204) {
        await response.body?.cancel();
        continue;
      }
      const chunks = [];
      let size = 0;
      for await (const chunk of response.body) {
        size += chunk.length;
        if (size > 131_072) throw new PublicError('Phản hồi MCP vượt giới hạn.');
        chunks.push(chunk);
      }
      const reply = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      if (message.method === 'initialize' && reply.result?.protocolVersion) {
        protocolVersion = reply.result.protocolVersion;
      }
      send(reply);
    } catch (error) {
      if (Object.hasOwn(message, 'id'))
        send({
          jsonrpc: '2.0',
          id: message.id,
          error: {
            code: -32000,
            message:
              error instanceof PublicError ? error.message : 'Không kết nối được MCP backend.',
          },
        });
    }
  }
}

function send(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

main().catch((error) => {
  process.stderr.write(
    `${error instanceof PublicError ? error.message : 'Không khởi động được MCP. Kiểm tra URL và kết nối backend.'}\n`,
  );
  process.exitCode = 1;
});
