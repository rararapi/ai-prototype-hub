import type { Operation, Sandbox, SystemInfo } from '../api';

export const sandboxFixture: Sandbox = {
  owner_email: 'owner@example.test', id: '00000000-0000-4000-8000-000000000001', name: 'Example app', template_id: 'hello-web',
  desired_state: 'stopped', status: 'stopped', generation: 0, active_operation_id: null,
  preview_url: null, expires_at: null, created_at: '2026-10-30T00:00:00Z',
  updated_at: '2026-10-30T00:00:00Z', error: null,
};
export const operationFixture: Operation = {
  id: '00000000-0000-4000-8000-000000000002', sandbox_id: sandboxFixture.id,
  action: 'start', generation: 1, status: 'queued', attempt_count: 0,
  created_at: sandboxFixture.created_at, updated_at: sandboxFixture.updated_at, error: null,
};
export const mockSystem: SystemInfo = {
  runtime_mode: 'mock', auth_mode: 'local-dev', constraints: ['Trusted templates only'],
};

export const loginFixture = { token: 'synthetic-owner-session', email: 'owner@example.test', expires_at: '2099-11-02T00:00:00Z' };
