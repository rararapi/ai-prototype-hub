import { ApiError } from './api';
import type { Action, CreateSandbox, LoginSession, Operation, Sandbox } from './api';

// This module is loaded only by the explicit static-demo build. No network or storage.
export const DEMO_EMAIL = 'demo@example.test';
export const DEMO_DELAY_MS = 900;
const timestamp = () => new Date().toISOString();

export function createDemo() {
  const records = new Map<string, Sandbox>();
  const operations = new Map<string, Operation>();
  const pending = new Map<string, number>();
  const latest = new Map<string, Operation>();
  const ttls = new Map<string, number>();
  const now = timestamp();
  const initialId = '00000000-0000-4000-8000-000000000001';
  records.set(initialId, {
    id: initialId, name: 'はじめてのサンプル', owner_email: DEMO_EMAIL,
    template_id: 'hello-web', desired_state: 'stopped', status: 'stopped',
    generation: 0, active_operation_id: null, preview_url: null, expires_at: null,
    created_at: now, updated_at: now, error: null,
  });
  ttls.set(initialId, 900);

  function get(id: string) {
    const record = records.get(id);
    if (!record) throw new ApiError('アプリが見つかりません。', 404);
    return record;
  }

  function action(id: string, requested: Action): Operation {
    const record = get(id);
    if (record.desired_state === 'deleted' && requested !== 'delete') {
      throw new ApiError('削除済みのアプリは操作できません。', 409);
    }
    const desired = requested === 'start' ? 'running' : requested === 'stop' ? 'stopped' : 'deleted';
    const active = latest.get(id);
    if (active && record.desired_state === desired
      && (active.status === 'queued' || active.status === 'running' || active.status === 'succeeded')) return active;
    if (active && ['queued', 'running'].includes(active.status)) {
      active.status = 'superseded';
      active.updated_at = timestamp();
      pending.delete(active.id);
    }
    record.generation += 1;
    record.desired_state = desired;
    record.status = requested === 'start' ? 'starting' : requested === 'stop' ? 'stopping' : 'deleting';
    record.preview_url = null;
    record.expires_at = null;
    record.updated_at = timestamp();
    const operation: Operation = {
      id: crypto.randomUUID(), sandbox_id: id, action: requested, generation: record.generation,
      status: 'queued', attempt_count: 0, error: null,
      created_at: timestamp(), updated_at: timestamp(),
    };
    record.active_operation_id = operation.id;
    operations.set(operation.id, operation);
    latest.set(id, operation);
    pending.set(operation.id, Date.now() + DEMO_DELAY_MS);
    return operation;
  }

  function settle() {
    for (const [id, readyAt] of pending) {
      if (Date.now() < readyAt) continue;
      const operation = operations.get(id)!;
      const record = get(operation.sandbox_id);
      pending.delete(id);
      if (record.generation !== operation.generation) { operation.status = 'superseded'; continue; }
      operation.status = 'succeeded';
      operation.attempt_count = 1;
      operation.updated_at = timestamp();
      record.status = record.desired_state;
      record.updated_at = timestamp();
      record.expires_at = record.status === 'running'
        ? new Date(Date.now() + ttls.get(record.id)! * 1000).toISOString() : null;
      record.active_operation_id = null;
    }
    for (const record of records.values()) {
      if (record.status === 'running' && record.expires_at && Date.parse(record.expires_at) <= Date.now()) {
        action(record.id, 'stop');
      }
    }
  }

  return async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    options.signal?.throwIfAborted();
    settle();
    const method = options.method ?? 'GET';
    let result: unknown;
    if (path === '/system') result = {
      runtime_mode: 'mock', auth_mode: 'local-dev',
      constraints: ['Browser-only public demo', 'No API, LLM or runtime calls'],
    };
    else if (path === '/templates') result = { items: [
      { id: 'hello-web', name: 'Hello Web', description: '信頼済みの固定サンプル' },
      { id: 'management-dashboard', name: '経営管理ダッシュボード', description: '売上・費用・利益と予実の画面見本' },
    ] };
    else if (path === '/auth/login') result = {
      token: 'public-demo-session', email: DEMO_EMAIL,
      expires_at: new Date(Date.now() + 86_400_000).toISOString(),
    } satisfies LoginSession;
    else if (path === '/auth/me') result = { email: DEMO_EMAIL };
    else if (path === '/auth/logout') result = { status: 'ok' };
    else if (path === '/sandboxes' && method === 'GET') {
      result = { items: [...records.values()].filter(record => record.status !== 'deleted') };
    } else if (path === '/sandboxes' && method === 'POST') {
      const payload = JSON.parse(String(options.body)) as CreateSandbox;
      if (typeof payload.name !== 'string' || !payload.name.trim() || payload.name.trim().length > 64
        || !['hello-web', 'management-dashboard'].includes(payload.template_id)
        || !Number.isInteger(payload.ttl_seconds) || payload.ttl_seconds < 60 || payload.ttl_seconds > 3600) {
        throw new ApiError('アプリ名・テンプレート・自動停止時間を確認してください。', 422);
      }
      const record: Sandbox = {
        id: crypto.randomUUID(), name: payload.name.trim(), owner_email: DEMO_EMAIL,
        template_id: payload.template_id, desired_state: 'stopped', status: 'stopped', generation: 0,
        active_operation_id: null, preview_url: null, expires_at: null, error: null,
        created_at: timestamp(), updated_at: timestamp(),
      };
      records.set(record.id, record);
      ttls.set(record.id, payload.ttl_seconds);
      result = record;
    } else if (path.startsWith('/operations/')) {
      result = operations.get(path.slice('/operations/'.length));
      if (!result) throw new ApiError('操作が見つかりません。', 404);
    } else {
      const match = /^\/sandboxes\/([^/]+)(?:\/(start|stop))?$/.exec(path);
      if (!match) throw new ApiError('この操作はデモでは利用できません。', 404);
      const [, id, requested] = match;
      result = method === 'DELETE' ? action(id, 'delete')
        : method === 'POST' && requested ? action(id, requested as Action) : get(id);
    }
    return structuredClone(result) as T;
  };
}

export const demoRequest = createDemo();
