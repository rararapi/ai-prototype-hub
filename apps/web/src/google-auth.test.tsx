import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from './App';
import { api, sessionStore } from './api';
import { registeredPreviewURL } from './GooglePreview';
import { loginFixture, mockSystem, sandboxFixture } from './test/fixtures';

const system = { ...mockSystem, auth_mode: 'google' as const, google_client_id: 'fixture.apps.googleusercontent.com',
  runtime_mode: 'real-kind' as const, preview_origin: 'http://localhost:8081' };
const session = { ...loginFixture, expires_at: new Date(Date.now() + 86_400_000).toISOString() };
type OAuth = NonNullable<NonNullable<NonNullable<Window['google']>['accounts']>['oauth2']>;

function stubGIS() {
  const requestCode = vi.fn();
  const initCodeClient = vi.fn<OAuth['initCodeClient']>(() => ({ requestCode }));
  vi.stubGlobal('google', { accounts: { oauth2: { initCodeClient } } });
  return { initCodeClient, requestCode };
}

beforeEach(() => {
  sessionStore.clear();
  vi.spyOn(api, 'system').mockResolvedValue(system);
  vi.spyOn(api, 'me').mockResolvedValue({ email: session.email });
  vi.spyOn(api, 'list').mockResolvedValue({ items: [] });
  vi.spyOn(api, 'templates').mockResolvedValue({ items: [] });
});

afterEach(() => { vi.unstubAllGlobals(); sessionStore.clear(); });

it('waits for the server auth mode, then signs in with a Google authorization code', async () => {
  const { initCodeClient, requestCode } = stubGIS();
  const login = vi.spyOn(api, 'googleLogin').mockResolvedValue(session);
  const dev = vi.spyOn(api, 'login');
  render(<App />);
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  const button = await screen.findByRole('button', { name: 'Google でログイン' });
  await waitFor(() => expect(button).toBeEnabled());
  expect(screen.queryByLabelText('メールアドレス')).not.toBeInTheDocument();
  expect(api.list).not.toHaveBeenCalled();
  await userEvent.click(button);
  expect(requestCode).toHaveBeenCalledOnce();
  const config = initCodeClient.mock.calls[0][0];
  expect(config).toMatchObject({ scope: 'openid email', client_id: system.google_client_id, ux_mode: 'popup' });
  act(() => config.callback({ code: 'fixture-code' }));
  expect(login).toHaveBeenCalledWith('fixture-code', expect.any(AbortSignal));
  expect(await screen.findByText('まだアプリがありません')).toBeInTheDocument();
  expect(sessionStore.get()).toEqual(session);
  expect(dev).not.toHaveBeenCalled();
});

it('explains consent denial or a closed popup and permits another attempt', async () => {
  const { initCodeClient } = stubGIS();
  const login = vi.spyOn(api, 'googleLogin');
  render(<App />);
  const button = await screen.findByRole('button', { name: 'Google でログイン' });
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
  const config = initCodeClient.mock.calls[0][0];
  act(() => config.error_callback({ type: 'popup_closed' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('閉じました');
  await userEvent.click(button);
  act(() => config.callback({ error: 'access_denied' }));
  expect(screen.getByRole('alert')).toHaveTextContent('許可されませんでした');
  expect(button).toBeEnabled();
  expect(login).not.toHaveBeenCalled();
});

it('uses the GIS SDK only in Google mode and permits retry after SDK failure', async () => {
  vi.mocked(api.system).mockResolvedValueOnce(mockSystem);
  const first = render(<App />);
  await screen.findByLabelText('メールアドレス');
  const script = () => document.querySelector<HTMLScriptElement>('script[src="https://accounts.google.com/gsi/client"]');
  expect(script()).toBeNull();
  first.unmount();
  render(<App />);
  await waitFor(() => expect(script()).not.toBeNull());
  expect(script()?.referrerPolicy).toBe('strict-origin-when-cross-origin');
  fireEvent.error(script()!);
  expect(await screen.findByRole('alert')).toHaveTextContent('読み込めませんでした');
  stubGIS();
  await userEvent.click(screen.getByRole('button', { name: '読み込みを再試行' }));
  expect(await screen.findByRole('button', { name: 'Google でログイン' })).toBeEnabled();
});

it('posts the code only to the console API with CSRF headers and no ambient credentials', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(session)));
  vi.stubGlobal('fetch', fetcher);
  await api.googleLogin('fixture-code');
  expect(fetcher).toHaveBeenCalledWith('/api/v1/auth/google', expect.objectContaining({
    method: 'POST', credentials: 'omit', redirect: 'error', body: JSON.stringify({ code: 'fixture-code' }),
    headers: expect.objectContaining({ 'X-Requested-With': 'XmlHttpRequest', 'X-ProtoHub-Client': 'console' }),
  }));
  expect(fetcher.mock.calls[0][1].headers.Authorization).toBeUndefined();
});

it('sends the current session when loading the registered-user template list', async () => {
  sessionStore.set(session);
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] })));
  vi.stubGlobal('fetch', fetcher);
  vi.mocked(api.templates).mockRestore();
  await api.templates();
  expect(fetcher).toHaveBeenCalledWith('/api/v1/templates', expect.objectContaining({
    headers: expect.objectContaining({ Authorization: 'Bearer ' + session.token }),
  }));
});

it('fetches the fixed sample from the configured origin and destroys its opaque iframe on logout', async () => {
  const row = { ...sandboxFixture, desired_state: 'running' as const, status: 'running' as const,
    preview_url: 'https://attacker.invalid/steal' };
  sessionStore.set(session);
  vi.mocked(api.list).mockResolvedValue({ items: [row] });
  vi.spyOn(api, 'logout').mockResolvedValue({ status: 'ok' });
  stubGIS();
  const fetcher = vi.fn().mockResolvedValue(new Response('<h1>Private fixture</h1>', {
    headers: { 'content-type': 'text/html; charset=utf-8' },
  }));
  vi.stubGlobal('fetch', fetcher);
  render(<App />);
  await userEvent.click(await screen.findByRole('button', { name: 'Example app の詳細' }));
  await userEvent.click(screen.getByRole('button', { name: 'アプリを開く' }));
  const iframe = await screen.findByTitle(row.name);
  expect(iframe).toHaveAttribute('sandbox', 'allow-scripts');
  expect(iframe.getAttribute('srcdoc')).toContain('Private fixture');
  expect(iframe.getAttribute('srcdoc')).not.toContain(session.token);
  expect(fetcher).toHaveBeenCalledWith(system.preview_origin + '/apps/' + row.id + '/', expect.objectContaining({
    credentials: 'omit', redirect: 'error', headers: { Accept: 'text/html', Authorization: 'Bearer ' + session.token },
  }));
  await userEvent.click(screen.getByRole('button', { name: '閉じる' }));
  expect(screen.queryByTitle(row.name)).toBeNull();
  await userEvent.click(screen.getByRole('button', { name: 'ログアウト' }));
  expect(sessionStore.get()).toBeNull();
});

it('keeps late preview responses out of a closed dialog and shows failed fetches', async () => {
  sessionStore.set(session);
  vi.mocked(api.list).mockResolvedValue({ items: [{ ...sandboxFixture, desired_state: 'running', status: 'running', preview_url: 'http://localhost/observed' }] });
  let resolve!: (response: Response) => void;
  const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }))
    .mockResolvedValueOnce(new Response(null, { status: 404 }));
  vi.stubGlobal('fetch', fetcher);
  render(<App />);
  await userEvent.click(await screen.findByRole('button', { name: 'Example app の詳細' }));
  const open = screen.getByRole('button', { name: 'アプリを開く' });
  await userEvent.click(open);
  await userEvent.click(screen.getByRole('button', { name: '閉じる' }));
  expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
  await act(async () => resolve(new Response('<h1>Late</h1>', { headers: { 'Content-Type': 'text/html' } })));
  await userEvent.click(open);
  expect(await screen.findByRole('alert')).toHaveTextContent('プレビューを開けません');
  expect(screen.queryByTitle(sandboxFixture.name)).toBeNull();
});

it('rejects insecure, noncanonical origins and IDs before constructing a preview URL', () => {
  for (const origin of ['http://cloud.example', 'https://trusted.invalid/path', 'https://user@trusted.invalid',
    'javascript:alert(1)', window.location.origin]) {
    expect(registeredPreviewURL(origin, sandboxFixture.id)).toBeNull();
  }
  expect(registeredPreviewURL(system.preview_origin, '../private')).toBeNull();
});
