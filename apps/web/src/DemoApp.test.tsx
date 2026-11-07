import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
vi.mock('./demo-mode', () => ({ IS_DEMO: true }));
import { SESSION_KEY } from './api';

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

it('lets visitors use the real UI without email, storage or any API/LLM request', async () => {
  vi.stubEnv('VITE_DEMO_MODE', 'true');
  const network = vi.fn(() => { throw new Error('Network forbidden'); });
  vi.stubGlobal('fetch', network);
  const { default: App } = await import('./App');
  render(<App />);
  expect(screen.getByRole('heading', { name: 'ProtoHub 操作デモ' })).toBeInTheDocument();
  expect(screen.queryByLabelText('メールアドレス')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '操作デモを始める' }));
  fireEvent.click(await screen.findByRole('button', { name: 'はじめてのサンプル の詳細' }));
  expect(screen.getByTestId('runtime-banner')).toHaveTextContent('操作デモ');
  fireEvent.click(screen.getByRole('button', { name: '共有設定' }));
  expect(await screen.findByRole('checkbox', { name: /メンバーA/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '閉じる' }));
  expect(screen.getByRole('link', { name: 'ProtoHub ホーム' })).toHaveAttribute('href', '/');
  fireEvent.click(screen.getByRole('button', { name: '起動' }));
  await waitFor(() => expect(screen.getByTestId('sandbox-status')).toHaveTextContent('模擬起動中'), { timeout: 5000 });
  expect(screen.getByRole('link', { name: /サンプル画面を見る/ })).toHaveAttribute('href', expect.stringContaining('/demo-preview.html#'));
  expect(screen.queryByRole('link', { name: /アプリを開く/ })).not.toBeInTheDocument();
  expect(sessionStorage.getItem(SESSION_KEY)).toBeNull();
  expect(network).not.toHaveBeenCalled();
}, 10000);
