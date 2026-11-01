import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { ApiError, api, sessionStore, SESSION_EXPIRED_EVENT } from './api';
import type { Operation, Sandbox } from './api';
import { loginFixture, mockSystem, operationFixture, sandboxFixture } from './test/fixtures';

let records: Sandbox[];
let detail: Sandbox;
let currentOperation: Operation;

beforeEach(() => {
  sessionStore.set({ ...loginFixture, expires_at: new Date(Date.now() + 86_400_000).toISOString() });
  vi.spyOn(api, 'me').mockResolvedValue({ email: loginFixture.email });
  vi.spyOn(api, 'login').mockImplementation(async email => ({ ...loginFixture, email: email.toLowerCase(), expires_at: new Date(Date.now() + 86_400_000).toISOString() }));
  vi.spyOn(api, 'logout').mockResolvedValue({ status: 'ok' });
  vi.spyOn(api, 'shares').mockResolvedValue({ emails: [] });
  vi.spyOn(api, 'setShares').mockImplementation(async (_id, emails) => ({ emails }));
  records = [];
  detail = { ...sandboxFixture };
  currentOperation = { ...operationFixture };
  vi.spyOn(api, 'system').mockResolvedValue(mockSystem);
  vi.spyOn(api, 'templates').mockResolvedValue({ items: [{ id: 'hello-web', name: 'Hello Web', description: 'Trusted local HTTP sample' }] });
  vi.spyOn(api, 'list').mockImplementation(async () => ({ items: records }));
  vi.spyOn(api, 'sandbox').mockImplementation(async () => detail);
  vi.spyOn(api, 'operation').mockImplementation(async () => currentOperation);
  vi.spyOn(api, 'create').mockImplementation(async input => {
    detail = { ...sandboxFixture, name: input.name };
    records = [detail];
    return detail;
  });
  vi.spyOn(api, 'action').mockImplementation(async (_id, action) => {
    currentOperation = { ...operationFixture, action };
    detail = { ...detail, active_operation_id: currentOperation.id,
      desired_state: action === 'start' ? 'running' : action === 'stop' ? 'stopped' : 'deleted',
      status: action === 'start' ? 'starting' : action === 'stop' ? 'stopping' : 'deleting', generation: 1 };
    records = [detail];
    return currentOperation;
  });
});

async function openDetail() {
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole('button', { name: 'Example app の詳細' }));
  return { user, panel: within(screen.getByTestId('sandbox-detail')) };
}

describe('ProtoHub management UI (mocked HTTP component tests)', () => {
  it('shows loading, empty state and the explicit mock banner', async () => {
    render(<App />);
    expect(screen.getByText('アプリを読み込み中…')).toBeInTheDocument();
    expect(await screen.findByText('まだアプリがありません')).toBeInTheDocument();
    expect(screen.getByText('Mock runtime — 実アプリは起動しません')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /アプリを開く/ })).not.toBeInTheDocument();
  });

  it('registers a fixed template and leaves the app stopped until an explicit start', async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText('まだアプリがありません');
    await user.click(screen.getAllByRole('button', { name: /サンプルを登録/ })[0]);
    const dialog = within(screen.getByRole('dialog', { name: 'サンプルアプリを登録' }));
    await user.type(dialog.getByLabelText('アプリ名'), 'First sample');
    expect(dialog.getByLabelText('テンプレート')).toHaveValue('hello-web');
    await user.clear(dialog.getByLabelText('自動停止までの時間（秒）'));
    await user.type(dialog.getByLabelText('自動停止までの時間（秒）'), '120');
    await user.click(dialog.getByRole('button', { name: '登録' }));
    expect(api.create).toHaveBeenCalledWith({ name: 'First sample', template_id: 'hello-web', ttl_seconds: 120 }, expect.any(AbortSignal));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByTestId('sandbox-status')).toHaveTextContent('停止中');
    expect(api.action).not.toHaveBeenCalled();
  });

  it('shows accepted start as starting, allows stop, and does not invent Ready', async () => {
    records = [detail];
    const { user, panel } = await openDetail();
    await user.click(panel.getByRole('button', { name: '起動' }));
    await waitFor(() => expect(screen.getByTestId('sandbox-status')).toHaveTextContent('起動中'));
    expect(screen.queryByRole('link', { name: /アプリを開く/ })).not.toBeInTheDocument();
    expect(panel.getByRole('button', { name: '停止' })).toBeEnabled();
    expect(panel.getByRole('button', { name: '起動' })).toBeDisabled();
    expect(screen.getByTestId('operation-status')).toHaveTextContent('起動 · 受付済み');
    await user.click(panel.getByRole('button', { name: '停止' }));
    await waitFor(() => expect(screen.getByTestId('sandbox-status')).toHaveTextContent('停止処理中'));
    expect(api.action).toHaveBeenLastCalledWith(detail.id, 'stop', expect.any(AbortSignal));
  });

  it('suppresses duplicate action submission while the first request is pending', async () => {
    records = [detail];
    let resolveOperation!: (operation: Operation) => void;
    vi.mocked(api.action).mockImplementation(() => new Promise(resolve => { resolveOperation = resolve; }));
    const { user, panel } = await openDetail();
    const start = panel.getByRole('button', { name: '起動' });
    await user.dblClick(start);
    expect(api.action).toHaveBeenCalledTimes(1);
    expect(start).toBeDisabled();
    await act(async () => { resolveOperation(operationFixture); });
    await waitFor(() => expect(start).toBeEnabled());
  });

  it('retains a failed mutation error while observation refresh succeeds', async () => {
    records = [detail];
    vi.mocked(api.action).mockRejectedValue(new ApiError('Operation rejected', 409, 'request-rejected'));
    const { user, panel } = await openDetail();
    await user.click(panel.getByRole('button', { name: '起動' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Operation rejected');
    await user.click(screen.getByRole('button', { name: '更新' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Operation rejected'));
    expect(screen.getByTestId('sandbox-status')).toHaveTextContent('停止中');
    expect(screen.queryByRole('link', { name: /アプリを開く/ })).not.toBeInTheDocument();
    expect(panel.getByRole('button', { name: '起動' })).toBeEnabled();
  });

  it('never offers a preview in mock mode even if the API supplies a URL', async () => {
    detail = { ...detail, status: 'running', desired_state: 'running', preview_url: 'http://localhost:8081/preview/example/' };
    records = [detail];
    await openDetail();
    expect(screen.getByTestId('sandbox-status')).toHaveTextContent('模擬起動中');
    expect(screen.queryByRole('link', { name: /アプリを開く/ })).not.toBeInTheDocument();
  });

  it('offers the observed local preview only when real mode reports running', async () => {
    vi.mocked(api.system).mockResolvedValue({ ...mockSystem, runtime_mode: 'real-kind' });
    detail = { ...detail, status: 'running', desired_state: 'running', preview_url: `http://localhost:8081/preview/${detail.id}/`, expires_at: '2026-10-30T00:15:00Z' };
    records = [detail];
    await openDetail();
    expect(screen.getByTestId('sandbox-status')).toHaveTextContent('Ready');
    expect(screen.getByRole('link', { name: /アプリを開く/ })).toHaveAttribute('href', detail.preview_url);
    expect(screen.getByTestId('expires-at')).not.toHaveTextContent('—');
  });

  it.each(['javascript:alert(1)', 'http://untrusted.invalid/preview/', 'http://user:password@localhost:8081/'])('rejects unsafe preview URL %s', async preview_url => {
    vi.mocked(api.system).mockResolvedValue({ ...mockSystem, runtime_mode: 'real-kind' });
    detail = { ...detail, status: 'running', desired_state: 'running', preview_url };
    records = [detail];
    await openDetail();
    expect(screen.queryByRole('link', { name: /アプリを開く/ })).not.toBeInTheDocument();
  });

  it('displays a runtime failure and allows a fresh start retry', async () => {
    detail = { ...detail, status: 'failed', desired_state: 'running', error: { code: 'readiness_timeout', message: 'Sample did not become ready in time' } };
    records = [detail];
    const { panel } = await openDetail();
    expect(panel.getByRole('alert')).toHaveTextContent('readiness_timeout');
    expect(panel.getByRole('button', { name: '起動' })).toBeEnabled();
  });

  it('confirms deletion by name, preserves the tombstone and prevents restart', async () => {
    records = [detail];
    vi.mocked(api.action).mockImplementation(async () => {
      detail = { ...detail, status: 'deleted', desired_state: 'deleted', active_operation_id: operationFixture.id };
      records = [];
      currentOperation = { ...operationFixture, action: 'delete', status: 'succeeded' };
      return currentOperation;
    });
    const { user, panel } = await openDetail();
    await user.click(panel.getByRole('button', { name: '削除' }));
    const dialog = within(screen.getByRole('dialog', { name: 'アプリを削除' }));
    expect(dialog.getByText('「Example app」')).toBeInTheDocument();
    expect(api.action).not.toHaveBeenCalled();
    await user.click(dialog.getByRole('button', { name: '削除する' }));
    await waitFor(() => expect(screen.getByTestId('sandbox-status')).toHaveTextContent('削除済み'));
    expect(panel.getByRole('button', { name: '起動' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Example app の詳細' })).not.toBeInTheDocument();
  });

  it('renders API errors and lets the user retry initial loading', async () => {
    vi.mocked(api.list).mockRejectedValueOnce(new ApiError('Database unavailable', 503, 'request-example'));
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Database unavailable');
    expect(screen.getByText('Request ID: request-example')).toBeInTheDocument();
    expect(screen.queryByText('まだアプリがありません')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '再試行' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });

  it('polls server observations and stops polling after unmount', async () => {
    records = [detail];
    vi.useFakeTimers();
    try {
      const { unmount } = render(<App />);
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      fireEvent.click(screen.getByRole('button', { name: 'Example app の詳細' }));
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      detail = { ...detail, status: 'stopped', generation: 2 };
      records = [detail];
      await act(async () => { await vi.advanceTimersByTimeAsync(1900); });
      expect(screen.getByTestId('sandbox-status')).toHaveTextContent('停止中');
      expect(screen.getByText('2', { selector: 'dd' })).toBeInTheDocument();
      unmount();
      const calls = vi.mocked(api.list).mock.calls.length;
      await vi.advanceTimersByTimeAsync(4000);
      expect(api.list).toHaveBeenCalledTimes(calls);
    } finally { vi.useRealTimers(); }
  });

  it('stops polling a terminal operation while continuing sandbox observation', async () => {
    detail = { ...detail, active_operation_id: operationFixture.id };
    records = [detail];
    currentOperation = { ...operationFixture, status: 'succeeded' };
    vi.useFakeTimers();
    try {
      render(<App />);
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      fireEvent.click(screen.getByRole('button', { name: 'Example app の詳細' }));
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(api.operation).toHaveBeenCalledTimes(1);
      const observations = vi.mocked(api.list).mock.calls.length;
      await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
      expect(api.operation).toHaveBeenCalledTimes(1);
      expect(vi.mocked(api.list).mock.calls.length).toBeGreaterThan(observations);
    } finally { vi.useRealTimers(); }
  });
});


describe('development login and app sharing', () => {
  it('requires email login before fetching private app data', async () => {
    sessionStore.clear();
    const user = userEvent.setup();
    render(<App />);
    expect(screen.getByRole('heading', { name: '開発用ログイン' })).toBeInTheDocument();
    expect(api.list).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText('メールアドレス'), 'owner@example.test');
    await user.click(screen.getByRole('button', { name: '開発用ログイン' }));
    expect(api.login).toHaveBeenCalledWith('owner@example.test', expect.any(AbortSignal));
    expect(await screen.findByText('まだアプリがありません')).toBeInTheDocument();
    expect(screen.getByText('owner@example.test')).toBeInTheDocument();
  });

  it('never offers login when the environment disables development auth', async () => {
    sessionStore.clear();
    vi.mocked(api.system).mockResolvedValue({ ...mockSystem, auth_mode: 'disabled' });
    render(<App />);
    expect(await screen.findByText('この環境では開発用ログインを利用できません。')).toBeInTheDocument();
    expect(screen.queryByLabelText('メールアドレス')).not.toBeInTheDocument();
    expect(api.list).not.toHaveBeenCalled();
  });

  it('shows shared apps as read-only and clears details when sharing is revoked', async () => {
    detail = { ...detail, owner_email: 'another@example.test' };
    records = [detail];
    const { user, panel } = await openDetail();
    expect(screen.getByRole('button', { name: 'Example app の詳細' })).toHaveTextContent('共有されたアプリ');
    for (const name of ['起動', '停止', '削除']) expect(panel.getByRole('button', { name })).toBeDisabled();
    expect(panel.queryByRole('button', { name: '共有設定' })).not.toBeInTheDocument();
    records = [];
    vi.mocked(api.sandbox).mockRejectedValue(new ApiError('Resource not found', 404));
    await user.click(screen.getByRole('button', { name: '更新' }));
    await waitFor(() => expect(screen.queryByTestId('sandbox-status')).not.toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Example app の詳細' })).not.toBeInTheDocument();
  });

  it('lets the owner replace or revoke the explicit recipient list', async () => {
    records = [detail];
    vi.mocked(api.shares).mockResolvedValue({ emails: ['reader@example.test'] });
    const { user, panel } = await openDetail();
    await user.click(panel.getByRole('button', { name: '共有設定' }));
    const dialog = within(screen.getByRole('dialog', { name: 'アプリの共有' }));
    const input = await dialog.findByLabelText('共有先のメールアドレス');
    await waitFor(() => expect(input).toHaveValue('reader@example.test'));
    await user.clear(input);
    await user.click(dialog.getByRole('button', { name: '共有を保存' }));
    expect(api.setShares).toHaveBeenCalledWith(detail.id, [], expect.any(AbortSignal));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByText('共有設定を保存しました。', { selector: 'p.inline-notice' })).toBeInTheDocument();
  });

  it('keeps keyboard focus inside the sharing dialog while saving disables its fields', async () => {
    records = [detail];
    let resolveSave!: (value: { emails: string[] }) => void;
    vi.mocked(api.setShares).mockImplementation(() => new Promise(resolve => { resolveSave = resolve; }));
    const { user, panel } = await openDetail();
    await user.click(panel.getByRole('button', { name: '共有設定' }));
    const dialog = within(screen.getByRole('dialog', { name: 'アプリの共有' }));
    await waitFor(() => expect(dialog.getByRole('button', { name: '共有を保存' })).toBeEnabled());
    await user.click(dialog.getByRole('button', { name: '共有を保存' }));
    expect(dialog.getByLabelText('共有先のメールアドレス')).toBeDisabled();
    const close = dialog.getByRole('button', { name: '閉じる' });
    close.focus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(close).toHaveFocus();
    await act(async () => { resolveSave({ emails: [] }); });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('does not allow overwriting shares after the current recipients fail to load', async () => {
    records = [detail];
    vi.mocked(api.shares).mockRejectedValue(new ApiError('Database unavailable', 503));
    const { user, panel } = await openDetail();
    await user.click(panel.getByRole('button', { name: '共有設定' }));
    const dialog = within(screen.getByRole('dialog', { name: 'アプリの共有' }));
    expect(await dialog.findByRole('alert')).toHaveTextContent('Database unavailable');
    expect(dialog.getByRole('button', { name: '共有を保存' })).toBeDisabled();
    expect(api.setShares).not.toHaveBeenCalled();
  });

  it('logout clears private state and ignores a late result from the old session', async () => {
    records = [detail];
    let resolveOld!: (value: { items: Sandbox[] }) => void;
    const { user } = await openDetail();
    vi.mocked(api.list).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    await user.click(screen.getByRole('button', { name: '更新' }));
    await user.click(screen.getByRole('button', { name: 'ログアウト' }));
    expect(sessionStore.get()).toBeNull();
    expect(screen.getByRole('heading', { name: '開発用ログイン' })).toBeInTheDocument();
    await act(async () => { resolveOld({ items: [detail] }); });
    expect(screen.queryByText('Example app')).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('メールアドレス'), 'next@example.test');
    records = [];
    await user.click(screen.getByRole('button', { name: '開発用ログイン' }));
    expect(await screen.findByText('まだアプリがありません')).toBeInTheDocument();
    expect(screen.queryByText('Example app')).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('reload validates the saved session before exposing private data', async () => {
    vi.mocked(api.me).mockRejectedValue(new ApiError('Session expired', 401));
    render(<App />);
    expect(screen.getByText('アプリを読み込み中…')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: '開発用ログイン' })).toBeInTheDocument();
    expect(api.list).not.toHaveBeenCalled();
    expect(sessionStore.get()).toBeNull();
  });

  it('logout aborts a pending registration and ignores its late response', async () => {
    let resolveOld!: (value: Sandbox) => void;
    vi.mocked(api.create).mockImplementation(() => new Promise(resolve => { resolveOld = resolve; }));
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText('まだアプリがありません');
    await user.click(screen.getAllByRole('button', { name: /サンプルを登録/ })[0]);
    const dialog = within(screen.getByRole('dialog', { name: 'サンプルアプリを登録' }));
    await user.type(dialog.getByLabelText('アプリ名'), 'Old session app');
    await user.click(dialog.getByRole('button', { name: '登録' }));
    const signal = vi.mocked(api.create).mock.calls[0][1];
    expect(signal?.aborted).toBe(false);
    await user.click(screen.getByRole('button', { name: 'ログアウト' }));
    expect(signal?.aborted).toBe(true);
    await act(async () => { resolveOld({ ...sandboxFixture, name: 'Old session app' }); });
    expect(screen.queryByText('Old session app')).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('a current-session 401 clears private data and returns to login', async () => {
    records = [detail];
    await openDetail();
    act(() => { window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT, { detail: sessionStore.get()?.token })); });
    expect(screen.getByRole('heading', { name: '開発用ログイン' })).toBeInTheDocument();
    expect(screen.queryByText('Example app')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('再度ログインしてください');
  });
});
