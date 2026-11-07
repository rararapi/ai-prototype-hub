import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError, sessionStore } from './api';
import { aiClient } from './ai-client';
import type { AiApplication, AiCreateRequest } from './ai-client';

const application: AiApplication = {
  id: '10000000-0000-4000-8000-000000000001',
  brief: { purpose: '予実を確認する', audience: '会議の参加者', success: '部門差を見つける' },
  config: { template: 'management-dashboard', title: '月次レポート', subtitle: '会議用の画面',
    color: 'blue', trend: true, departments: true, cash_flow: false },
  summary: '部門の比較を中心にしました。', model: 'gemini-3.5-flash-lite', status: 'draft',
  revision: 1, usage: { input_tokens: 200, output_tokens: 100 },
  created_at: '2026-11-07T00:00:00Z', updated_at: '2026-11-07T00:00:00Z',
};
const payload: AiCreateRequest = {
  request_id: '20000000-0000-4000-8000-000000000001',
  brief: application.brief, config: application.config, instruction: '部門を比較しやすく',
};
const network = vi.fn<typeof fetch>();
beforeEach(() => {
  sessionStore.set({ token: 'test-session-token', email: 'demo@example.test',
    expires_at: new Date(Date.now() + 3600000).toISOString() });
  vi.stubGlobal('fetch', network);
  network.mockReset();
});
afterEach(() => { sessionStore.clear(); vi.unstubAllGlobals(); });

it('uses the authenticated same-origin API for persisted list and detail, with escaped IDs', async () => {
  network.mockResolvedValueOnce(Response.json({ items: [application] })).mockResolvedValueOnce(Response.json(application));
  const controller = new AbortController();
  expect(await aiClient.list(controller.signal)).toEqual({ items: [application] });
  expect(await aiClient.get('id/../../', controller.signal)).toEqual(application);
  expect(network.mock.calls[0][0]).toBe('/api/v1/ai/apps');
  expect(network.mock.calls[1][0]).toBe('/api/v1/ai/apps/id%2F..%2F..%2F');
  const options = network.mock.calls[0][1]!;
  expect(new Headers(options.headers).get('Authorization')).toBe('Bearer test-session-token');
  expect(options).toMatchObject({ credentials: 'omit', cache: 'no-store', redirect: 'error', signal: controller.signal });
});

it('sends typed create, revise, confirm and delete requests without an LLM request from the browser', async () => {
  network.mockImplementation(async (_url, options) => Response.json(options?.method === 'DELETE' ? { status: 'ok' } : application));
  const controller = new AbortController();
  await aiClient.create(payload, controller.signal);
  await aiClient.revise(application.id, { request_id: payload.request_id, expected_revision: 1, instruction: '緑に変更' }, controller.signal);
  await aiClient.confirm(application.id, 2, controller.signal);
  await aiClient.remove(application.id, controller.signal);
  const calls = network.mock.calls;
  expect(calls.map(([url]) => url)).toEqual([
    '/api/v1/ai/apps', '/api/v1/ai/apps/' + application.id + '/revise',
    '/api/v1/ai/apps/' + application.id + '/confirm', '/api/v1/ai/apps/' + application.id,
  ]);
  expect(calls.map(([, options]) => options?.method)).toEqual(['POST', 'POST', 'POST', 'DELETE']);
  expect(JSON.parse(calls[0][1]!.body as string)).toEqual(payload);
  expect(JSON.parse(calls[2][1]!.body as string)).toEqual({ expected_revision: 2 });
  expect(calls[3][1]!.body).toBe('{}');
  for (const [, options] of calls) {
    const headers = new Headers(options!.headers);
    expect(headers.get('X-ProtoHub-Client')).toBe('console');
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(options!.signal).toBe(controller.signal);
  }
});

it('exposes a definite upstream error once instead of retrying or returning a mock result', async () => {
  network.mockResolvedValueOnce(Response.json({ error: { code: 'ai_unavailable', message: 'Gemini unavailable', request_id: 'safe-request' } }, { status: 503 }));
  await expect(aiClient.create(payload)).rejects.toMatchObject({ status: 503, requestId: 'safe-request' });
  expect(network).toHaveBeenCalledTimes(1);
});

it('preserves cancellation so closing the studio does not turn an abort into a retryable model error', async () => {
  const controller = new AbortController();
  controller.abort();
  const abort = new DOMException('aborted', 'AbortError');
  network.mockRejectedValueOnce(abort);
  await expect(aiClient.create(payload, controller.signal)).rejects.toBe(abort);
  expect(network).toHaveBeenCalledTimes(1);
  expect(abort).not.toBeInstanceOf(ApiError);
});

it.each(['create', 'revise'] as const)('preserves invalid_response from a truncated successful %s body', async action => {
  const status = action === 'create' ? 201 : 200;
  network.mockResolvedValueOnce(new Response('{"id":', { status,
    headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'after-commit' } }));
  const call = action === 'create' ? aiClient.create(payload)
    : aiClient.revise(application.id, { request_id: payload.request_id, expected_revision: 1, instruction: '緑に変更' });
  await expect(call).rejects.toMatchObject({ status, code: 'invalid_response', requestId: 'after-commit' });
  expect(network).toHaveBeenCalledTimes(1);
});

it.each(['create', 'revise'] as const)('rejects valid JSON with a malformed config after successful %s', async action => {
  const status = action === 'create' ? 201 : 200;
  network.mockResolvedValueOnce(Response.json({ ...application, config: { ...application.config, color: 'url(https://untrusted.invalid)' } }, { status }));
  const call = action === 'create' ? aiClient.create(payload)
    : aiClient.revise(application.id, { request_id: payload.request_id, expected_revision: 1, instruction: '緑に変更' });
  await expect(call).rejects.toMatchObject({ status, code: 'invalid_response' });
  expect(network).toHaveBeenCalledTimes(1);
});

const invalidPlans: [string, unknown][] = [
  ['null', null],
  ['non-object', []],
  ['missing application field', { ...application, usage: undefined }],
  ['unexpected application field', { ...application, executable: 'do not run' }],
  ['invalid UUID', { ...application, id: 'not-a-uuid' }],
  ['empty brief', { ...application, brief: { ...application.brief, purpose: ' ' } }],
  ['oversized brief', { ...application, brief: { ...application.brief, audience: 'a'.repeat(301) } }],
  ['unknown template', { ...application, config: { ...application.config, template: 'uploaded-code' } }],
  ['empty title', { ...application, config: { ...application.config, title: ' ' } }],
  ['oversized subtitle', { ...application, config: { ...application.config, subtitle: 'a'.repeat(161) } }],
  ['string boolean', { ...application, config: { ...application.config, trend: 'false' } }],
  ['unknown config field', { ...application, config: { ...application.config, upstream_url: 'https://untrusted.invalid' } }],
  ['page with dashboard flags', { ...application, config: { ...application.config, template: 'hello-web' } }],
  ['empty model', { ...application, model: ' ' }],
  ['oversized summary', { ...application, summary: 'a'.repeat(1001) }],
  ['runtime status', { ...application, status: 'running' }],
  ['zero revision', { ...application, revision: 0 }],
  ['fractional revision', { ...application, revision: 1.5 }],
  ['unsafe revision', { ...application, revision: Number.MAX_SAFE_INTEGER + 1 }],
  ['negative usage', { ...application, usage: { input_tokens: -1, output_tokens: 1 } }],
  ['fractional usage', { ...application, usage: { input_tokens: 1, output_tokens: 0.5 } }],
  ['boolean usage', { ...application, usage: { input_tokens: true, output_tokens: 1 } }],
  ['date without timezone', { ...application, created_at: '2026-11-07T00:00:00' }],
  ['invalid date', { ...application, updated_at: '2026-13-07T00:00:00Z' }],
  ['calendar rollover', { ...application, updated_at: '2026-02-31T00:00:00Z' }],
  ['midnight rollover', { ...application, updated_at: '2026-11-07T24:00:00Z' }],
  ['non-leap day', { ...application, updated_at: '2025-02-29T00:00:00Z' }],
];

it.each(invalidPlans)('does not return an unvalidated application for %s', async (_label, value) => {
  network.mockResolvedValueOnce(Response.json(value, { status: 201 }));
  await expect(aiClient.create(payload)).rejects.toMatchObject({ status: 201, code: 'invalid_response' });
  expect(network).toHaveBeenCalledTimes(1);
});

const invalidLists: [string, unknown][] = [
  ['null', null], ['array', []], ['missing items', {}], ['non-array items', { items: null }],
  ['invalid application', { items: [{ ...application, config: { ...application.config, color: 'red' } }] }],
  ['duplicate identifiers', { items: [application, application] }],
  ['unexpected list field', { items: [], executable: 'do not run' }],
];

it.each(invalidLists)('rejects an invalid saved-list shape: %s', async (_label, value) => {
  network.mockResolvedValueOnce(Response.json(value));
  await expect(aiClient.list()).rejects.toMatchObject({ status: 200, code: 'invalid_response' });
});

it('accepts valid bounded Unicode, nullable usage and a timezone-qualified timestamp', async () => {
  const value = { ...application, brief: { ...application.brief, purpose: '😀'.repeat(300) },
    config: { ...application.config, title: '😀'.repeat(64), subtitle: '😀'.repeat(160) },
    summary: '😀'.repeat(1000), usage: null, updated_at: '2026-11-07T09:00:00+09:00' };
  network.mockResolvedValueOnce(Response.json(value));
  expect(await aiClient.get(application.id)).toEqual(value);
});

it('validates each saved app without adding an unsupported collection-size limit', async () => {
  const items = Array.from({ length: 1001 }, (_, index) => ({ ...application,
    id: '10000000-0000-4000-8000-' + index.toString(16).padStart(12, '0') }));
  network.mockResolvedValueOnce(Response.json({ items }));
  expect((await aiClient.list()).items).toHaveLength(1001);
});

it('requires the successful delete result before confirming local removal', async () => {
  network.mockResolvedValueOnce(Response.json({ status: 'failed' }));
  await expect(aiClient.remove(application.id)).rejects.toMatchObject({ status: 200, code: 'invalid_response' });
});

it('accepts a real leap-day timestamp', async () => {
  const value = { ...application, created_at: '2024-02-29T00:00:00Z', updated_at: '2024-02-29T00:00:00Z' };
  network.mockResolvedValueOnce(Response.json(value));
  expect(await aiClient.get(application.id)).toEqual(value);
});
