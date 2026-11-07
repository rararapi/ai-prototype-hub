import { IS_DEMO } from './demo-mode';
import type { components } from './generated/api';

// The second template exists only in the static demo; backend/generated contracts stay fixed.
export type TemplateId = 'hello-web' | 'management-dashboard';
export type Sandbox = Omit<components['schemas']['Sandbox'], 'template_id'> & { template_id: TemplateId };
export type Operation = components['schemas']['Operation'];
export type SystemInfo = components['schemas']['SystemInfo'];
export type Template = Omit<components['schemas']['Template'], 'id'> & { id: TemplateId };
export type CreateSandbox = Omit<components['schemas']['CreateSandbox'], 'template_id'> & { template_id: TemplateId };
export type LoginSession = components['schemas']['LoginSession'];
export type Principal = components['schemas']['Principal'];
export type ShareList = components['schemas']['ShareList'];
type SandboxList = { items: Sandbox[] };
type TemplateList = { items: Template[] };
type HttpError = components['schemas']['HttpError'];
export type Action = 'start' | 'stop' | 'delete';

export class ApiError extends Error {
  readonly status: number;
  readonly requestId?: string;
  readonly code?: string;

  constructor(message: string, status: number, requestId?: string, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.requestId = requestId;
    this.code = code;
  }
}

export const SESSION_KEY = 'protohub.dev-session.v1';
export const SESSION_EXPIRED_EVENT = 'protohub-session-expired';

let demoSession: LoginSession | null = null;

export const sessionStore = {
  get(): LoginSession | null {
    if (IS_DEMO) return demoSession;
    try {
      const value: unknown = JSON.parse(window.sessionStorage.getItem(SESSION_KEY) ?? 'null');
      if (typeof value === 'object' && value !== null && 'token' in value && 'email' in value && 'expires_at' in value
        && typeof value.token === 'string' && value.token.length > 0
        && typeof value.email === 'string' && value.email.length > 0
        && typeof value.expires_at === 'string' && Date.parse(value.expires_at) > Date.now()) {
        return { token: value.token, email: value.email, expires_at: value.expires_at };
      }
      window.sessionStorage.removeItem(SESSION_KEY);
    } catch { /* Storage may be unavailable; remain logged out. */ }
    return null;
  },
  set(session: LoginSession): void {
    if (IS_DEMO) { demoSession = session; return; }
    window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  },
  clear(): void {
    if (IS_DEMO) { demoSession = null; return; }
    try { window.sessionStorage.removeItem(SESSION_KEY); } catch { /* Already inaccessible. */ }
  },
};

export async function request<T>(path: string, options: RequestInit = {}, authenticated = true): Promise<T> {
  if (import.meta.env.VITE_DEMO_MODE === 'true') {
    const { demoRequest } = await import('./demo');
    return demoRequest<T>(path, options);
  }
  const token = authenticated ? sessionStore.get()?.token : undefined;
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      credentials: 'omit',
      cache: 'no-store',
      redirect: 'error',
      ...options,
      headers: {
        Accept: 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
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
    if (response.status === 401 && token && sessionStore.get()?.token === token) {
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT, { detail: token }));
    }
    const body = await response.json().catch(() => null) as HttpError | null;
    throw new ApiError(
      body?.error?.message || `リクエストに失敗しました（HTTP ${response.status}）。`,
      response.status,
      body?.error?.request_id,
      body?.error?.code,
    );
  }
  try {
    return await response.json() as T;
  } catch {
    throw new ApiError('APIから有効なJSONを受信できませんでした。', response.status, response.headers.get('X-Request-ID') ?? undefined, 'invalid_response');
  }
}

const idPath = (id: string) => `/sandboxes/${encodeURIComponent(id)}`;

export const api = {
  login: (email: string, signal?: AbortSignal) => request<LoginSession>('/auth/login', {
    method: 'POST', body: JSON.stringify({ email }), signal,
  }, false),
  googleLogin: (code: string, signal?: AbortSignal) => request<LoginSession>('/auth/google', {
    method: 'POST', body: JSON.stringify({ code }), signal,
    headers: { 'X-Requested-With': 'XmlHttpRequest' },
  }, false),
  me: (signal?: AbortSignal) => request<Principal>('/auth/me', { signal }),
  logout: () => request<{ status: 'ok' }>('/auth/logout', { method: 'POST', body: '{}' }),
  shares: (id: string, signal?: AbortSignal) => request<ShareList>(`${idPath(id)}/shares`, { signal }),
  setShares: (id: string, emails: string[], signal?: AbortSignal) => request<ShareList>(`${idPath(id)}/shares`, {
    method: 'PUT', body: JSON.stringify({ emails }), signal,
  }),
  system: (signal?: AbortSignal) => request<SystemInfo>('/system', { signal }, false),
  templates: (signal?: AbortSignal) => request<TemplateList>('/templates', { signal }),
  list: (signal?: AbortSignal) => request<SandboxList>('/sandboxes', { signal }),
  sandbox: (id: string, signal?: AbortSignal) => request<Sandbox>(idPath(id), { signal }),
  operation: (id: string, signal?: AbortSignal) =>
    request<Operation>(`/operations/${encodeURIComponent(id)}`, { signal }),
  create: (payload: CreateSandbox, signal?: AbortSignal): Promise<Sandbox> => {
    if (payload.template_id !== 'hello-web' && import.meta.env.VITE_DEMO_MODE !== 'true') {
      return Promise.reject(new ApiError('このテンプレートは操作デモ専用です。', 422));
    }
    return request<Sandbox>('/sandboxes', { method: 'POST', body: JSON.stringify(payload), signal });
  },
  action: (id: string, action: Action, signal?: AbortSignal) => request<Operation>(
    action === 'delete' ? idPath(id) : `${idPath(id)}/${action}`,
    { method: action === 'delete' ? 'DELETE' : 'POST', body: '{}', signal },
  ),
};
