import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api } from './api';
import { operationFixture, sandboxFixture } from './test/fixtures';

afterEach(() => { vi.unstubAllGlobals(); });

describe('typed API client', () => {
  it('sends JSON and the custom client header for registration', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(sandboxFixture), { status: 201 }));
    vi.stubGlobal('fetch', fetchMock);
    await api.create({ name: 'Example app', template_id: 'hello-web', ttl_seconds: 900 });
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/sandboxes', expect.objectContaining({
      method: 'POST', credentials: 'same-origin',
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
  it('retains safe API error message and request ID', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: {
      code: 'state_conflict', message: 'Deleted application cannot be started', request_id: 'request-example',
    } }), { status: 409 })));
    await expect(api.action(sandboxFixture.id, 'start')).rejects.toMatchObject({
      message: 'Deleted application cannot be started', status: 409, requestId: 'request-example',
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
