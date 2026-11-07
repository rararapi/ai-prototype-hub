import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import DemoBuilder from './DemoBuilder';
import DemoPreview from './DemoPreview';
import { defaultConfig, seedDraft } from './demo-builder';
import { sandboxFixture } from './test/fixtures';

afterEach(() => { vi.useRealTimers(); });

it('reflects iterative instructions in the financial preview and supports undo without fetch', async () => {
  const fetchSpy = vi.spyOn(globalThis, 'fetch');
  const id = 'builder-ui';
  seedDraft(id, 'management-dashboard', '利益推移グラフを追加');
  render(<DemoBuilder sandbox={{ ...sandboxFixture, id, template_id: 'management-dashboard', status: 'running' }} />);
  const canvas = within(screen.getByTestId('demo-canvas'));
  expect(canvas.getByText('売上')).toBeInTheDocument();
  expect(canvas.getByText('費用')).toBeInTheDocument();
  expect(canvas.getByText('営業利益')).toBeInTheDocument();
  expect(canvas.getByRole('img', { name: /営業利益.*6か月/ })).toBeInTheDocument();
  vi.useFakeTimers();
  fireEvent.click(screen.getByRole('button', { name: '部門別の表を追加' }));
  expect(screen.getByRole('button', { name: '部門別の表を追加' })).toBeDisabled();
  await act(async () => { await vi.advanceTimersByTimeAsync(700); });
  expect(canvas.getByRole('table')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '青い配色に変更' }));
  await act(async () => { await vi.advanceTimersByTimeAsync(700); });
  expect(screen.getByTestId('demo-canvas')).toHaveClass('theme-blue');
  fireEvent.click(screen.getByRole('button', { name: 'ひとつ戻す' }));
  expect(screen.getByTestId('demo-canvas')).toHaveClass('theme-purple');
  expect(canvas.getByRole('table')).toBeInTheDocument();
  expect(fetchSpy).not.toHaveBeenCalled();
});

it('cancels a pending refinement on unmount rather than changing another app', async () => {
  const id = 'cancel-builder-ui';
  seedDraft(id, 'management-dashboard');
  vi.useFakeTimers();
  const view = render(<DemoBuilder sandbox={{ ...sandboxFixture, id, template_id: 'management-dashboard' }} />);
  fireEvent.click(screen.getByRole('button', { name: '部門別の表を追加' }));
  view.unmount();
  await act(async () => { await vi.advanceTimersByTimeAsync(700); });
  vi.useRealTimers();
  render(<DemoBuilder sandbox={{ ...sandboxFixture, id, template_id: 'management-dashboard' }} />);
  await waitFor(() => expect(screen.queryByRole('table')).not.toBeInTheDocument());
});

it('renders instructed copy as plain text and labels all figures as sample data', () => {
  const title = '<img src=x onerror=alert(1)>';
  const { container } = render(<DemoPreview config={{ ...defaultConfig('management-dashboard'), title }} />);
  expect(screen.getByRole('heading', { name: title })).toBeInTheDocument();
  expect(container.querySelector('img')).toBeNull();
  expect(screen.getByText('架空のサンプルデータ')).toBeInTheDocument();
});
