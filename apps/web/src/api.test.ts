import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, sessionStore, SESSION_KEY, SESSION_EXPIRED_EVENT } from './api';
import { loginFixture, operationFixture, sandboxFixture } from './test/fixtures';

beforeEach(() => { sessionStore.set({ ...loginFixture, expires_at: new Date(Date.now() + 86_400_000).toISOString() }); });
afterEach(() => { sessionStore.clear(); vi.unstubAllGlobals(); });

describe('typed API client', () => {
  it('sends JSON and the custom client header for registration', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(sandboxFixture), { status: 201 }));
    vi.stubGlobal('fetch', fetchMock);
    await api.create({ name: 'Example app', template_id: 'hello-web', ttl_seconds: 900 });
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/sandboxes', expect.objectContaining({
      method: 'POST', credentials: 'omit',
      headers: expect.objectContaining({ 'Content-Type': 'application/json', 'X-ProtoHub-Client': 'console' }),
      body: JSON.stringify({ name: 'Example app', template_id: 'hello-web', ttl_seconds: 900 }),
    }));
  });
  it.each(['start', 'stop', 'delete'] as const)('sends %s as a mutation with JSON', async action => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(operationFixture), { status: 202 }));
    vi.stubGlobal('fetch', fetchMock);
    await api.action(sandboxFixture.id, action);
    const suffix = action === 'delete' ? '' : `/${action}`;
    expect(fetchMock).toHaveBeenCalledWith(`/api/v1/sandboxes/${sandboxFixture.id}${suffix}`, expect.objectContaining({
      method: action === 'delete' ? 'DELETE' : 'POST', body: '{}',
      headers: expect.objectContaining({ 'X-ProtoHub-Client': 'console' }),
    }));
  });
  it('rejects the demo-only template before any normal API request', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    await expect(api.create({ name: 'Demo only', template_id: 'management-dashboard', ttl_seconds: 900 })).rejects.toMatchObject({ status: 422 });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('retains safe API error message and request ID', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: {
      code: 'state_conflict', message: 'Deleted application cannot be started', request_id: 'request-example',
    } }), { status: 409 })));
    await expect(api.action(sandboxFixture.id, 'start')).rejects.toMatchObject({
      message: 'Deleted application cannot be started', status: 409, requestId: 'request-example', code: 'state_conflict',
    });
  });
  it('handles non-JSON errors and network failure without leaking raw diagnostics', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response('<html>proxy error</html>', { status: 503 }))
      .mockRejectedValueOnce(new TypeError('private proxy diagnostic'));
    vi.stubGlobal('fetch', fetchMock);
    await expect(api.list()).rejects.toThrow('HTTP 503');
    try { await api.list(); } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as Error).message).not.toContain('private proxy');
    }
  });
  it('passes cancellation through to the caller', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('cancelled', 'AbortError')));
    await expect(api.list()).rejects.toMatchObject({ name: 'AbortError' });
  });
});


describe('development session boundaries', () => {
  it('attaches bearer tokens only to protected same-origin API paths and omits cookies', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{}'));
    vi.stubGlobal('fetch', fetchMock);
    await api.list();
    await api.system();
    await api.login('owner@example.test');
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: 'omit', headers: { Authorization: `Bearer ${loginFixture.token}` } });
    for (const call of fetchMock.mock.calls.slice(1)) expect(call[1].headers).not.toHaveProperty('Authorization');
    expect(fetchMock.mock.calls.every(call => call[0].startsWith('/api/v1/'))).toBe(true);
  });

  it('rejects corrupt and expired saved sessions', () => {
    sessionStorage.setItem(SESSION_KEY, '{');
    expect(sessionStore.get()).toBeNull();
    sessionStorage.setItem(SESSION_KEY, JSON.stringify({ ...loginFixture, expires_at: '2000-01-01T00:00:00Z' }));
    expect(sessionStore.get()).toBeNull();
    sessionStorage.setItem(SESSION_KEY, JSON.stringify({ ...loginFixture, token: 1 }));
    expect(sessionStore.get()).toBeNull();
  });

  it('notifies only the still-current session when an unauthorized response arrives', async () => {
    let resolve!: (value: Response) => void;
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise(done => { resolve = done; })));
    const listener = vi.fn();
    window.addEventListener(SESSION_EXPIRED_EVENT, listener);
    try {
      const pending = api.list();
      sessionStore.set({ ...loginFixture, token: 'another-session', expires_at: new Date(Date.now() + 86_400_000).toISOString() });
      resolve(new Response('{}', { status: 401 }));
      await expect(pending).rejects.toMatchObject({ status: 401 });
      expect(listener).not.toHaveBeenCalled();
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 401 })));
      await expect(api.list()).rejects.toMatchObject({ status: 401 });
      expect(listener).toHaveBeenCalledTimes(1);
    } finally { window.removeEventListener(SESSION_EXPIRED_EVENT, listener); }
  });

  it('replaces shares with a JSON PUT and encoded resource ID', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ emails: [] })));
    vi.stubGlobal('fetch', fetchMock);
    await api.setShares('test/id', []);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/sandboxes/test%2Fid/shares', expect.objectContaining({ method: 'PUT', body: '{"emails":[]}', headers: expect.objectContaining({ 'X-ProtoHub-Client': 'console', Authorization: `Bearer ${loginFixture.token}` }) }));
  });
});

it.each(['dependency_unavailable', 'ai_generation_failed'])('preserves the safe %s code to distinguish ambiguous and terminal generation failures', async code => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: {
    code, message: 'Generation unavailable', request_id: 'synthetic-request',
  } }), { status: 503 })));
  await expect(api.list()).rejects.toMatchObject({ status: 503, code, requestId: 'synthetic-request' });
});

it.each([200, 201])('identifies a truncated successful HTTP%s body without losing ambiguous-result status', async status => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{', { status })));
  await expect(api.list()).rejects.toMatchObject({ status, code: 'invalid_response' });
});
