import type { components } from './generated/api';

export type Sandbox = components['schemas']['Sandbox'];
export type Operation = components['schemas']['Operation'];
export type SystemInfo = components['schemas']['SystemInfo'];
export type Template = components['schemas']['Template'];
export type CreateSandbox = components['schemas']['CreateSandbox'];
type SandboxList = components['schemas']['SandboxList'];
type TemplateList = components['schemas']['TemplateList'];
type HttpError = components['schemas']['HttpError'];
export type Action = 'start' | 'stop' | 'delete';

export class ApiError extends Error {
  readonly status: number;
  readonly requestId?: string;

  constructor(message: string, status: number, requestId?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.requestId = requestId;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      credentials: 'same-origin',
      ...options,
      headers: {
        Accept: 'application/json',
        ...(options.method && options.method !== 'GET'
          ? { 'Content-Type': 'application/json', 'X-ProtoHub-Client': 'console' }
          : {}),
        ...options.headers,
      },
    });
  } catch (error) {
    if (typeof error === 'object' && error !== null && 'name' in error && error.name === 'AbortError') throw error;
    throw new ApiError('APIに接続できません。ローカル環境の起動状態を確認してください。', 0);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null) as HttpError | null;
    throw new ApiError(
      body?.error?.message || `リクエストに失敗しました（HTTP ${response.status}）。`,
      response.status,
      body?.error?.request_id,
    );
  }
  try {
    return await response.json() as T;
  } catch {
    throw new ApiError('APIから有効なJSONを受信できませんでした。', response.status);
  }
}

const idPath = (id: string) => `/sandboxes/${encodeURIComponent(id)}`;

export const api = {
  system: (signal?: AbortSignal) => request<SystemInfo>('/system', { signal }),
  templates: (signal?: AbortSignal) => request<TemplateList>('/templates', { signal }),
  list: (signal?: AbortSignal) => request<SandboxList>('/sandboxes', { signal }),
  sandbox: (id: string, signal?: AbortSignal) => request<Sandbox>(idPath(id), { signal }),
  operation: (id: string, signal?: AbortSignal) =>
    request<Operation>(`/operations/${encodeURIComponent(id)}`, { signal }),
  create: (payload: CreateSandbox) => request<Sandbox>('/sandboxes', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  action: (id: string, action: Action) => request<Operation>(
    action === 'delete' ? idPath(id) : `${idPath(id)}/${action}`,
    { method: action === 'delete' ? 'DELETE' : 'POST', body: '{}' },
  ),
};
