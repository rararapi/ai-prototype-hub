import { fireEvent, render, screen, within } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import DemoCreation from './DemoCreation';

function fillIntent() {
  fireEvent.change(screen.getByLabelText('何をできるようにしたいですか？'), { target: { value: '月次会議で予実を確認する' } });
  fireEvent.change(screen.getByLabelText('誰が使いますか？'), { target: { value: '会議の参加者' } });
  fireEvent.click(screen.getByRole('button', { name: '画面の内容を決める' }));
}
function fillSuccess() {
  fireEvent.change(screen.getByLabelText('画面見本で、どんなことを確かめたいですか？'), { target: { value: '部門ごとの差が分かるか' } });
  fireEvent.click(screen.getByRole('button', { name: '作成内容を確認' }));
}

it('focuses a missing decision and never creates before the user reviews all decisions', () => {
  const create = vi.fn();
  render(<DemoCreation busy={false} onCreate={create} />);
  fireEvent.click(screen.getByRole('button', { name: '画面の内容を決める' }));
  expect(screen.getByLabelText('何をできるようにしたいですか？')).toHaveFocus();
  expect(screen.getAllByText('内容を入力してください。')).toHaveLength(2);
  expect(create).not.toHaveBeenCalled();
  fillIntent();
  fireEvent.click(screen.getByRole('button', { name: '作成内容を確認' }));
  expect(screen.getByLabelText('画面見本で、どんなことを確かめたいですか？')).toHaveFocus();
  expect(screen.queryByRole('button', { name: 'この内容で画面見本を作成' })).not.toBeInTheDocument();
  expect(create).not.toHaveBeenCalled();
});

it('reviews exact selected features, supports correction, and hands off a structured plan without fetch', () => {
  const create = vi.fn();
  const network = vi.spyOn(globalThis, 'fetch');
  render(<DemoCreation busy={false} onCreate={create} />);
  fireEvent.change(screen.getByLabelText('アプリ名'), { target: { value: '「青い部門」の確認' } });
  fillIntent();
  fireEvent.click(screen.getByRole('checkbox', { name: '部門別の表' }));
  fireEvent.click(screen.getByRole('radio', { name: '青' }));
  fillSuccess();
  expect(screen.getByText('月次会議で予実を確認する')).toBeInTheDocument();
  expect(screen.getByText('売上・費用・利益と予実を、ひと目で。')).toBeInTheDocument();
  expect(screen.getByText('部門別の表を表示する')).toBeInTheDocument();
  expect(screen.getByText(/テストの合格/)).toBeInTheDocument();
  expect(create).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '前の内容を修正' }));
  expect(screen.getByLabelText('画面見本で、どんなことを確かめたいですか？')).toHaveValue('部門ごとの差が分かるか');
  fireEvent.click(screen.getByRole('checkbox', { name: '部門別の表' }));
  fireEvent.click(screen.getByRole('button', { name: '作成内容を確認' }));
  expect(screen.queryByText('部門別の表を表示する')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'この内容で画面見本を作成' }));
  expect(create).toHaveBeenCalledExactlyOnceWith('「青い部門」の確認', 'management-dashboard', 900, '', expect.objectContaining({
    profile: 'trusted-preview-v1',
    config: expect.objectContaining({ title: '「青い部門」の確認', departments: false, color: 'blue' }),
    brief: expect.objectContaining({ audience: '会議の参加者' }),
  }));
  expect(network).not.toHaveBeenCalled();
});

it('asks only applicable questions and keeps business answers when changing the screen type', () => {
  render(<DemoCreation busy={false} onCreate={vi.fn()} />);
  fillIntent();
  fireEvent.click(screen.getByRole('checkbox', { name: '部門別の表' }));
  fireEvent.click(screen.getByRole('button', { name: '前の内容を修正' }));
  expect(screen.getByLabelText('誰が使いますか？')).toHaveValue('会議の参加者');
  fireEvent.click(screen.getByRole('radio', { name: /案内用のWebページ/ }));
  fireEvent.click(screen.getByRole('button', { name: '画面の内容を決める' }));
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/データベース|Kubernetes|APIキー/)).not.toBeInTheDocument();
  fillSuccess();
  expect(screen.getByText('案内用のWebページを表示する')).toBeInTheDocument();
  expect(screen.queryByText('部門別の表を表示する')).not.toBeInTheDocument();
});

it('prevents edits and duplicate submission while creation is pending', () => {
  const create = vi.fn();
  const view = render(<DemoCreation busy={false} onCreate={create} />);
  fillIntent();
  fillSuccess();
  view.rerender(<DemoCreation busy onCreate={create} />);
  expect(screen.getByRole('button', { name: '作成中…' })).toBeDisabled();
  expect(screen.getByRole('button', { name: '前の内容を修正' })).toBeDisabled();
  fireEvent.submit(screen.getByRole('button', { name: '作成中…' }).closest('form')!);
  expect(create).not.toHaveBeenCalled();
  const steps = within(screen.getByRole('list', { name: '作成の手順' })).getAllByRole('listitem');
  expect(steps[2]).toHaveAttribute('aria-current', 'step');
});

it('shows an explicitly empty description in the reviewed plan', () => {
  render(<DemoCreation busy={false} onCreate={vi.fn()} />);
  fillIntent();
  fireEvent.change(screen.getByLabelText('画面に表示する説明文'), { target: { value: '  ' } });
  fillSuccess();
  expect(screen.getByText('説明文なし')).toBeInTheDocument();
  expect(screen.queryByText('説明文を表示する')).not.toBeInTheDocument();
});
