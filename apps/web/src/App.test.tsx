import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { ApiError, api } from './api';
import type { Operation, Sandbox } from './api';
import { mockSystem, operationFixture, sandboxFixture } from './test/fixtures';

let records: Sandbox[];
let detail: Sandbox;
let currentOperation: Operation;

beforeEach(() => {
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
    expect(api.create).toHaveBeenCalledWith({ name: 'First sample', template_id: 'hello-web', ttl_seconds: 120 });
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
    expect(api.action).toHaveBeenLastCalledWith(detail.id, 'stop');
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
