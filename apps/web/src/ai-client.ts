import { ApiError, request } from './api';
import type { components } from './generated/api';

export type AiBrief = components['schemas']['AiBrief'];
export type AiConfig = components['schemas']['AiConfig'];
export type AiApplication = components['schemas']['AiApplication'];
export type AiCreateRequest = components['schemas']['AiCreateRequest'];
export type AiReviseRequest = components['schemas']['AiReviseRequest'];
const appPath = (id: string) => '/ai/apps/' + encodeURIComponent(id);
const uuid = /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i;
const timestamp = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/;

function fields(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    && Object.keys(value).length === keys.length
    && keys.every(key => Object.prototype.hasOwnProperty.call(value, key));
}
function text(value: unknown, min: number, max: number): value is string {
  if (typeof value !== 'string' || value.length > max * 2) return false;
  const length = [...value].length;
  return length >= min && length <= max && (min === 0 || value.trim().length > 0);
}
function count(value: unknown, min = 0): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= min;
}
function isTimestamp(value: unknown): value is string {
  if (typeof value !== 'string' || value.length > 40 || !timestamp.test(value)) return false;
  const year = Number(value.slice(0, 4)), month = Number(value.slice(5, 7)), day = Number(value.slice(8, 10));
  if (year < 1 || month < 1 || month > 12) return false;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day >= 1 && day <= days[month - 1] && Number(value.slice(11, 13)) < 24
    && Number(value.slice(14, 16)) < 60 && Number(value.slice(17, 19)) < 60
    && Number.isFinite(Date.parse(value));
}
function isBrief(value: unknown): value is AiBrief {
  return fields(value, ['purpose', 'audience', 'success'])
    && text(value.purpose, 1, 300) && text(value.audience, 1, 300) && text(value.success, 1, 300);
}
function isConfig(value: unknown): value is AiConfig {
  return fields(value, ['template', 'title', 'subtitle', 'color', 'trend', 'departments', 'cash_flow'])
    && (value.template === 'hello-web' || value.template === 'management-dashboard')
    && text(value.title, 1, 64) && text(value.subtitle, 0, 160)
    && (value.color === 'purple' || value.color === 'blue' || value.color === 'green')
    && typeof value.trend === 'boolean' && typeof value.departments === 'boolean' && typeof value.cash_flow === 'boolean'
    && (value.template !== 'hello-web' || (!value.trend && !value.departments && !value.cash_flow));
}
function isUsage(value: unknown): value is AiApplication['usage'] {
  return value === null || (fields(value, ['input_tokens', 'output_tokens'])
    && count(value.input_tokens) && count(value.output_tokens));
}
function isApplication(value: unknown): value is AiApplication {
  return fields(value, ['id', 'brief', 'config', 'summary', 'model', 'status', 'revision', 'usage', 'created_at', 'updated_at'])
    && typeof value.id === 'string' && uuid.test(value.id)
    && isBrief(value.brief) && isConfig(value.config) && text(value.summary, 0, 1000) && text(value.model, 1, 128)
    && (value.status === 'draft' || value.status === 'ready') && count(value.revision, 1) && isUsage(value.usage)
    && isTimestamp(value.created_at) && isTimestamp(value.updated_at);
}
function invalidResponse(status: number): never {
  throw new ApiError('APIから有効な画面案を受信できませんでした。', status, undefined, 'invalid_response');
}
function applicationResponse(value: unknown, status: number): AiApplication {
  if (!isApplication(value)) return invalidResponse(status);
  return { ...value, brief: { ...value.brief }, config: { ...value.config },
    usage: value.usage === null ? null : { ...value.usage } };
}
async function applicationRequest(path: string, options: RequestInit, status = 200): Promise<AiApplication> {
  return applicationResponse(await request<unknown>(path, options), status);
}

export const aiClient = {
  list: async (signal?: AbortSignal): Promise<components['schemas']['AiApplicationList']> => {
    const result = await request<unknown>('/ai/apps', { signal });
    if (!fields(result, ['items']) || !Array.isArray(result.items)) return invalidResponse(200);
    const items: unknown[] = result.items;
    const seen = new Set<string>();
    const applications = items.map(item => {
      const application = applicationResponse(item, 200);
      if (seen.has(application.id)) return invalidResponse(200);
      seen.add(application.id);
      return application;
    });
    return { items: applications };
  },
  get: (id: string, signal?: AbortSignal) => applicationRequest(appPath(id), { signal }),
  create: (payload: AiCreateRequest, signal?: AbortSignal) => applicationRequest('/ai/apps', {
    method: 'POST', body: JSON.stringify(payload), signal,
  }, 201),
  revise: (id: string, payload: AiReviseRequest, signal?: AbortSignal) => applicationRequest(appPath(id) + '/revise', {
    method: 'POST', body: JSON.stringify(payload), signal,
  }),
  confirm: (id: string, expectedRevision: number, signal?: AbortSignal) => applicationRequest(appPath(id) + '/confirm', {
    method: 'POST', body: JSON.stringify({ expected_revision: expectedRevision }), signal,
  }),
  remove: async (id: string, signal?: AbortSignal): Promise<{ status: 'ok' }> => {
    const result = await request<unknown>(appPath(id), { method: 'DELETE', body: '{}', signal });
    if (!fields(result, ['status']) || result.status !== 'ok') return invalidResponse(200);
    return { status: 'ok' };
  },
};
