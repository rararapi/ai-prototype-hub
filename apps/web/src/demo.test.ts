import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createDemo, DEMO_DELAY_MS } from './demo';
import type { Operation, Sandbox } from './api';

let request: ReturnType<typeof createDemo>;
const payload = { name: 'デモ用アプリ', template_id: 'hello-web', ttl_seconds: 60 };
const post = (body: unknown) => ({ method: 'POST', body: JSON.stringify(body) });
const read = (id: string) => request<Sandbox>(`/sandboxes/${id}`);
const create = () => request<Sandbox>('/sandboxes', post(payload));
const action = (id: string, name: string) => request<Operation>(`/sandboxes/${id}/${name}`, post({}));
const advance = () => vi.advanceTimersByTime(DEMO_DELAY_MS);

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-11-04T00:00:00Z'));
  vi.stubGlobal('fetch', vi.fn(() => { throw new Error('Network forbidden'); }));
  request = createDemo();
});
afterEach(() => { expect(fetch).not.toHaveBeenCalled(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('browser-only demo lifecycle', () => {
  it('registers, starts, stops and deletes while never issuing a real preview URL', async () => {
    const record = await create();
    expect(record.status).toBe('stopped');
    const start = await action(record.id, 'start');
    expect(start.status).toBe('queued');
    expect((await read(record.id)).status).toBe('starting');
    advance();
    expect(await read(record.id)).toMatchObject({ status: 'running', preview_url: null });
    expect(await request(`/operations/${start.id}`)).toMatchObject({ status: 'succeeded' });
    await action(record.id, 'stop');
    advance();
    expect(await read(record.id)).toMatchObject({ status: 'stopped', expires_at: null });
    await request(`/sandboxes/${record.id}`, { method: 'DELETE' });
    advance();
    expect((await read(record.id)).status).toBe('deleted');
    const list = await request<{ items: Sandbox[] }>('/sandboxes');
    expect(list.items.some(item => item.id === record.id)).toBe(false);
    await expect(action(record.id, 'start')).rejects.toMatchObject({ status: 409 });
  });

  it.each(['stop', 'delete'])('a later %s supersedes a pending start and cannot be resurrected', async name => {
    const record = await create();
    const start = await action(record.id, 'start');
    const next = name === 'delete'
      ? await request<Operation>(`/sandboxes/${record.id}`, { method: 'DELETE' })
      : await action(record.id, 'stop');
    advance();
    expect(await request(`/operations/${start.id}`)).toMatchObject({ status: 'superseded' });
    expect(await read(record.id)).toMatchObject({ status: name === 'delete' ? 'deleted' : 'stopped', generation: next.generation });
    vi.advanceTimersByTime(5000);
    expect((await read(record.id)).desired_state).not.toBe('running');
  });

  it('deduplicates retries and starts the TTL only after simulated completion', async () => {
    const record = await create();
    const first = await action(record.id, 'start');
    expect((await action(record.id, 'start')).id).toBe(first.id);
    vi.advanceTimersByTime(60_000);
    const running = await read(record.id);
    expect(running.status).toBe('running');
    expect(Date.parse(running.expires_at!) - Date.now()).toBe(60_000);
    expect((await action(record.id, 'start')).id).toBe(first.id);
    vi.advanceTimersByTime(60_000);
    expect((await read(record.id)).status).toBe('stopping');
    advance();
    expect((await read(record.id)).status).toBe('stopped');
  });

  it('lists both fixed templates and creates the management template without a backend', async () => {
    const templates = await request<{ items: { id: string }[] }>('/templates');
    expect(templates.items.map(item => item.id)).toEqual(['hello-web', 'management-dashboard']);
    const record = await request<Sandbox>('/sandboxes', post({ ...payload, template_id: 'management-dashboard' }));
    expect(record.template_id).toBe('management-dashboard');
  });

  it('aborted mutations do not change state, and callers receive detached objects', async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(request('/sandboxes', { ...post(payload), signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' });
    const record = await create();
    record.name = 'Changed by caller';
    expect((await read(record.id)).name).toBe(payload.name);
  });

  it('resets to only the initial sample in a fresh page and rejects arbitrary templates', async () => {
    await create();
    const fresh = createDemo();
    expect((await fresh<{ items: Sandbox[] }>('/sandboxes')).items).toHaveLength(1);
    await expect(request('/sandboxes', post({ ...payload, template_id: 'arbitrary-image' }))).rejects.toMatchObject({ status: 422 });
  });
});
