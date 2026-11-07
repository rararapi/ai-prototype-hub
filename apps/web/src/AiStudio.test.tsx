import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { ApiError } from './api';
import AiStudio from './AiStudio';
import { aiClient } from './ai-client';
import type { AiApplication } from './ai-client';

vi.mock('./ai-client', () => ({
  aiClient: { list: vi.fn(), get: vi.fn(), create: vi.fn(), revise: vi.fn(), confirm: vi.fn(), remove: vi.fn() },
}));
const application: AiApplication = {
  id: '10000000-0000-4000-8000-000000000001',
  brief: { purpose: '月次会議で予実を確認する', audience: '会議の参加者', success: '部門ごとの差を見つける' },
  config: { template: 'management-dashboard', title: 'Geminiによる月次レポート', subtitle: '部門ごとの比較に使う画面',
    color: 'blue', trend: true, departments: true, cash_flow: false },
  summary: '部門別の表と推移グラフを中心にしました。', model: 'gemini-3.5-flash-lite',
  status: 'draft', revision: 1, usage: { input_tokens: 200, output_tokens: 100 },
  created_at: '2026-11-07T00:00:00Z', updated_at: '2026-11-07T00:00:00Z',
};

beforeEach(() => {
  vi.mocked(aiClient.list).mockResolvedValue({ items: [] });
  vi.mocked(aiClient.get).mockResolvedValue(application);
  vi.mocked(aiClient.create).mockResolvedValue(application);
  vi.mocked(aiClient.revise).mockResolvedValue({ ...application, revision: 2, config: { ...application.config, color: 'green' } });
  vi.mocked(aiClient.confirm).mockResolvedValue({ ...application, status: 'ready' });
  vi.mocked(aiClient.remove).mockResolvedValue({ status: 'ok' });
});

function continueToDetails(purpose = application.brief.purpose) {
  fireEvent.change(screen.getByLabelText('作りたいアプリ・実現したいこと'), { target: { value: purpose } });
  fireEvent.click(screen.getByRole('button', { name: 'つづける' }));
}

function fillBrief() {
  if (screen.queryByLabelText('作りたいアプリ・実現したいこと')) continueToDetails();
  fireEvent.change(screen.getByLabelText('アプリ名'), { target: { value: '希望した名前' } });
  fireEvent.change(screen.getByLabelText('何をできるようにしたいですか？'), { target: { value: application.brief.purpose } });
  fireEvent.change(screen.getByLabelText('誰が使いますか？'), { target: { value: application.brief.audience } });
  fireEvent.change(screen.getByLabelText('画面見本で、どんなことを確かめたいですか？'), { target: { value: application.brief.success } });
}
async function createPlan() {
  await screen.findByText(/まだ画面案はありません/);
  fillBrief();
  fireEvent.click(screen.getByRole('button', { name: 'Geminiで画面案を生成' }));
  await screen.findByRole('heading', { name: '生成結果の確認' });
}
async function resume() {
  vi.mocked(aiClient.list).mockResolvedValue({ items: [application] });
  render(<AiStudio />);
  fireEvent.click(await screen.findByRole('button', { name: /Geminiによる月次レポート/ }));
  await screen.findByRole('heading', { name: '生成結果の確認' });
}

it('starts with one empty idea field and no preset dashboard or model write', async () => {
  render(<AiStudio />);
  await screen.findByText(/まだ画面案はありません/);
  expect(screen.getByRole('heading', { name: 'どんなアプリを作りたいですか？' })).toBeInTheDocument();
  const idea = screen.getByLabelText('作りたいアプリ・実現したいこと');
  expect(idea).toHaveValue('');
  expect(idea).toHaveAttribute('placeholder', expect.stringContaining('例:'));
  expect(idea).toHaveAttribute('maxlength', '300');
  expect(screen.getAllByRole('textbox')).toHaveLength(1);
  expect(screen.queryByText('経営管理ダッシュボード')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('アプリ名')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Geminiで画面案を生成' })).not.toBeInTheDocument();
  expect(screen.getByText(/画面案を生成すると、入力内容をGeminiへ送信/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'つづける' }));
  expect(idea).toHaveFocus();
  expect(screen.getByText('作りたいことを入力してください。')).toBeInTheDocument();
  expect(aiClient.create).not.toHaveBeenCalled();
  expect(aiClient.revise).not.toHaveBeenCalled();
  expect(aiClient.confirm).not.toHaveBeenCalled();
  expect(aiClient.remove).not.toHaveBeenCalled();
  expect(screen.queryByTestId('ai-canvas')).not.toBeInTheDocument();
});

it('requires a trimmed idea of at most 300 characters before locally continuing', async () => {
  render(<AiStudio />);
  await screen.findByText(/まだ画面案はありません/);
  continueToDetails('   ');
  expect(screen.queryByLabelText('アプリ名')).not.toBeInTheDocument();
  continueToDetails('あ'.repeat(301));
  expect(screen.getByLabelText('作りたいアプリ・実現したいこと')).toHaveFocus();
  expect(screen.getByText('300文字以内で入力してください。', { selector: '.ai-field-error' })).toBeInTheDocument();
  continueToDetails('  参加申込を受け付けたい  ');
  expect(screen.getByLabelText('何をできるようにしたいですか？')).toHaveValue('参加申込を受け付けたい');
  for (const label of ['アプリ名', '画面の説明文', '誰が使いますか？', '画面見本で、どんなことを確かめたいですか？']) {
    expect(screen.getByLabelText(label)).toHaveValue('');
  }
  expect(screen.getByLabelText('最初に試す画面')).toHaveValue('hello-web');
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(aiClient.create).not.toHaveBeenCalled();
  expect(aiClient.revise).not.toHaveBeenCalled();
  expect(aiClient.confirm).not.toHaveBeenCalled();
  expect(aiClient.remove).not.toHaveBeenCalled();
});

it('preserves explicit details when editing the idea and only enables dashboard flags by choice', async () => {
  render(<AiStudio />);
  await screen.findByText(/まだ画面案はありません/);
  fillBrief();
  fireEvent.change(screen.getByLabelText('画面の説明文'), { target: { value: '自分で入力した説明文' } });
  fireEvent.change(screen.getByLabelText('最初の追加要望（任意）'), { target: { value: '見出しを短く' } });
  fireEvent.change(screen.getByLabelText('最初に試す画面'), { target: { value: 'management-dashboard' } });
  for (const checkbox of screen.getAllByRole('checkbox')) expect(checkbox).not.toBeChecked();
  fireEvent.click(screen.getByRole('checkbox', { name: '部門別の表' }));
  fireEvent.click(screen.getByRole('button', { name: '作りたいことを編集' }));
  expect(screen.getAllByRole('textbox')).toHaveLength(1);
  expect(screen.getByLabelText('作りたいアプリ・実現したいこと')).toHaveValue(application.brief.purpose);
  continueToDetails('参加申込の管理もしたい');
  expect(screen.getByLabelText('何をできるようにしたいですか？')).toHaveValue('参加申込の管理もしたい');
  expect(screen.getByLabelText('アプリ名')).toHaveValue('希望した名前');
  expect(screen.getByLabelText('画面の説明文')).toHaveValue('自分で入力した説明文');
  expect(screen.getByLabelText('誰が使いますか？')).toHaveValue(application.brief.audience);
  expect(screen.getByLabelText('画面見本で、どんなことを確かめたいですか？')).toHaveValue(application.brief.success);
  expect(screen.getByLabelText('最初の追加要望（任意）')).toHaveValue('見出しを短く');
  expect(screen.getByRole('checkbox', { name: '部門別の表' })).toBeChecked();
  expect(aiClient.create).not.toHaveBeenCalled();
});

it('requires a user supplied app name and missing decisions before generating', async () => {
  render(<AiStudio />);
  await screen.findByText(/まだ画面案はありません/);
  continueToDetails();
  fireEvent.click(screen.getByRole('button', { name: 'Geminiで画面案を生成' }));
  expect(screen.getByLabelText('アプリ名')).toHaveFocus();
  expect(screen.getByText('アプリ名を入力してください。')).toBeInTheDocument();
  expect(screen.getAllByText('内容を入力してください。')).toHaveLength(2);
  expect(aiClient.create).not.toHaveBeenCalled();
});

it('starts a new empty idea after a saved plan without copying model generated defaults', async () => {
  await resume();
  fireEvent.click(screen.getByRole('button', { name: '新しい画面案' }));
  expect(screen.getByLabelText('作りたいアプリ・実現したいこと')).toHaveValue('');
  continueToDetails('イベントの案内を作りたい');
  expect(screen.getByLabelText('アプリ名')).toHaveValue('');
  expect(screen.getByLabelText('画面の説明文')).toHaveValue('');
  expect(screen.getByLabelText('最初に試す画面')).toHaveValue('hello-web');
  expect(aiClient.create).not.toHaveBeenCalled();
});

it('preserves an unsent human draft while resuming and leaving a saved plan', async () => {
  vi.mocked(aiClient.list).mockResolvedValue({ items: [application] });
  render(<AiStudio />);
  fillBrief();
  fireEvent.click(await screen.findByRole('button', { name: /Geminiによる月次レポート/ }));
  await screen.findByRole('heading', { name: '生成結果の確認' });
  fireEvent.click(screen.getByRole('button', { name: '新しい画面案' }));
  expect(screen.getByLabelText('作りたいアプリ・実現したいこと')).toHaveValue(application.brief.purpose);
  fireEvent.click(screen.getByRole('button', { name: 'つづける' }));
  expect(screen.getByLabelText('アプリ名')).toHaveValue('希望した名前');
  expect(aiClient.create).not.toHaveBeenCalled();
});

it('reviews the actual generated result and confirms only its revision without another generation call', async () => {
  render(<AiStudio />);
  await createPlan();
  const canvas = within(screen.getByTestId('ai-canvas'));
  expect(canvas.getByRole('heading', { name: application.config.title })).toBeInTheDocument();
  expect(canvas.getByText(application.config.subtitle)).toBeInTheDocument();
  expect(canvas.getByRole('table')).toBeInTheDocument();
  expect(screen.getByText(application.summary)).toBeInTheDocument();
  expect(screen.getByText(application.model)).toBeInTheDocument();
  expect(screen.queryByText('希望した名前')).not.toBeInTheDocument();
  expect(aiClient.create).toHaveBeenCalledWith(expect.objectContaining({
    request_id: expect.any(String), brief: application.brief,
    config: expect.objectContaining({ title: '希望した名前' }),
  }), expect.any(AbortSignal));
  expect(aiClient.confirm).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'この内容で確定' }));
  await screen.findByRole('heading', { name: '確認済みの画面案' });
  expect(aiClient.confirm).toHaveBeenCalledWith(application.id, 1, expect.any(AbortSignal));
  expect(aiClient.create).toHaveBeenCalledTimes(1);
  expect(aiClient.revise).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: '確認済みとして保存済み' })).toBeDisabled();
});

it('resumes server-saved plans and uses the latest generated revision for confirmation', async () => {
  await resume();
  fireEvent.change(screen.getByLabelText('追加の指示・修正したいこと'), { target: { value: '緑の配色に変更' } });
  fireEvent.click(screen.getByRole('button', { name: 'Geminiに修正を依頼' }));
  await waitFor(() => expect(screen.getByTestId('ai-canvas')).toHaveClass('theme-green'));
  expect(aiClient.revise).toHaveBeenCalledWith(application.id, expect.objectContaining({ expected_revision: 1, instruction: '緑の配色に変更' }), expect.any(AbortSignal));
  expect(screen.getByLabelText('追加の指示・修正したいこと')).toHaveValue('');
  vi.mocked(aiClient.confirm).mockResolvedValue({ ...application, revision: 2, status: 'ready', config: { ...application.config, color: 'green' } });
  fireEvent.click(screen.getByRole('button', { name: 'この内容で確定' }));
  await screen.findByRole('heading', { name: '確認済みの画面案' });
  expect(aiClient.confirm).toHaveBeenLastCalledWith(application.id, 2, expect.any(AbortSignal));
  expect(aiClient.create).not.toHaveBeenCalled();
});

it('keeps the same request ID for an ambiguous retry, but edits create a new request ID', async () => {
  vi.mocked(aiClient.create).mockRejectedValue(new ApiError('connection lost', 0));
  render(<AiStudio />);
  await screen.findByText(/まだ画面案はありません/);
  fillBrief();
  fireEvent.click(screen.getByRole('button', { name: 'Geminiで画面案を生成' }));
  await screen.findByRole('alert');
  const first = vi.mocked(aiClient.create).mock.calls[0][0];
  fireEvent.click(screen.getByRole('button', { name: 'Geminiで画面案を生成' }));
  await waitFor(() => expect(aiClient.create).toHaveBeenCalledTimes(2));
  await screen.findByRole('alert');
  expect(vi.mocked(aiClient.create).mock.calls[1][0]).toEqual(first);
  fireEvent.change(screen.getByLabelText('アプリ名'), { target: { value: '変更した名前' } });
  fireEvent.click(screen.getByRole('button', { name: 'Geminiで画面案を生成' }));
  await waitFor(() => expect(aiClient.create).toHaveBeenCalledTimes(3));
  expect(vi.mocked(aiClient.create).mock.calls[2][0].request_id).not.toBe(first.request_id);
});

it.each([429, 503])('retains form and exposes a definite %s without fallback or automatic retry', async status => {
  vi.mocked(aiClient.create).mockRejectedValue(new ApiError('safe upstream failure', status, undefined, status === 503 ? 'ai_generation_failed' : undefined));
  render(<AiStudio />);
  await screen.findByText(/まだ画面案はありません/);
  fillBrief();
  fireEvent.click(screen.getByRole('button', { name: 'Geminiで画面案を生成' }));
  const error = await screen.findByRole('alert');
  expect(error).toHaveTextContent(status === 429 ? '上限' : '生成に失敗');
  expect(screen.getByLabelText('何をできるようにしたいですか？')).toHaveValue(application.brief.purpose);
  expect(screen.queryByTestId('ai-canvas')).not.toBeInTheDocument();
  expect(aiClient.create).toHaveBeenCalledTimes(1);
  const firstId = vi.mocked(aiClient.create).mock.calls[0][0].request_id;
  vi.mocked(aiClient.create).mockResolvedValue(application);
  fireEvent.click(screen.getByRole('button', { name: 'Geminiで画面案を生成' }));
  await screen.findByRole('heading', { name: '生成結果の確認' });
  expect(vi.mocked(aiClient.create).mock.calls[1][0].request_id).not.toBe(firstId);
});

it('does not apply a stale revision and refreshes only after an explicit request while preserving the instruction', async () => {
  await resume();
  vi.mocked(aiClient.revise).mockRejectedValue(new ApiError('revision conflict', 409));
  fireEvent.change(screen.getByLabelText('追加の指示・修正したいこと'), { target: { value: '緑の配色に変更' } });
  fireEvent.click(screen.getByRole('button', { name: 'Geminiに修正を依頼' }));
  await screen.findByRole('alert');
  expect(screen.getByTestId('ai-canvas')).toHaveClass('theme-blue');
  expect(screen.getByLabelText('追加の指示・修正したいこと')).toHaveValue('緑の配色に変更');
  expect(aiClient.get).toHaveBeenCalledTimes(1);
  vi.mocked(aiClient.get).mockResolvedValue({ ...application, revision: 3 });
  fireEvent.click(screen.getByRole('button', { name: '最新の画面案を読み直す' }));
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  expect(screen.getByLabelText('追加の指示・修正したいこと')).toHaveValue('緑の配色に変更');
  vi.mocked(aiClient.revise).mockResolvedValue({ ...application, revision: 4 });
  fireEvent.click(screen.getByRole('button', { name: 'Geminiに修正を依頼' }));
  await waitFor(() => expect(aiClient.revise).toHaveBeenCalledTimes(2));
  expect(vi.mocked(aiClient.revise).mock.calls[1][1].expected_revision).toBe(3);
});

it('prevents duplicate generation while pending and aborts the request on unmount', async () => {
  let finish!: (value: AiApplication) => void;
  vi.mocked(aiClient.create).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const view = render(<AiStudio />);
  await screen.findByText(/まだ画面案はありません/);
  fillBrief();
  const form = screen.getByRole('button', { name: 'Geminiで画面案を生成' }).closest('form')!;
  fireEvent.submit(form);
  fireEvent.submit(form);
  expect(aiClient.create).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'Geminiで生成中…' })).toBeDisabled();
  const signal = vi.mocked(aiClient.create).mock.calls[0][1]!;
  view.unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => { finish(application); });
});

it('keeps generation available when listing failed and ignores an older in-flight list result', async () => {
  let finishList!: (value: { items: AiApplication[] }) => void;
  vi.mocked(aiClient.list).mockImplementation(() => new Promise(resolve => { finishList = resolve; }));
  render(<AiStudio />);
  fillBrief();
  fireEvent.click(screen.getByRole('button', { name: 'Geminiで画面案を生成' }));
  await screen.findByRole('heading', { name: '生成結果の確認' });
  await act(async () => { finishList({ items: [] }); });
  expect(screen.getByRole('button', { name: /Geminiによる月次レポート/ })).toBeInTheDocument();
});

it('renders model copy as plain text and confirms a named deletion before calling the API', async () => {
  const title = '<img src=x onerror=alert(1)>';
  vi.mocked(aiClient.list).mockResolvedValue({ items: [{ ...application, config: { ...application.config, title } }] });
  vi.mocked(aiClient.get).mockResolvedValue({ ...application, config: { ...application.config, title }, summary: '<script>alert(1)</script>' });
  const view = render(<AiStudio />);
  fireEvent.click(await screen.findByRole('button', { name: new RegExp('img src=x') }));
  await screen.findByRole('heading', { name: '生成結果の確認' });
  expect(view.container.querySelector('img,script')).toBeNull();
  expect(screen.getByText('<script>alert(1)</script>')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '画面案を削除' }));
  const confirmation = within(screen.getByRole('region', { name: '削除の確認' }));
  expect(confirmation.getByText(/img src=x/)).toBeInTheDocument();
  expect(aiClient.remove).not.toHaveBeenCalled();
  fireEvent.click(confirmation.getByRole('button', { name: '削除する' }));
  await waitFor(() => expect(screen.queryByTestId('ai-canvas')).not.toBeInTheDocument());
  expect(aiClient.remove).toHaveBeenCalledWith(application.id, expect.any(AbortSignal));
});

it('shows only relevant options for a simple page and sends no dashboard flags', async () => {
  render(<AiStudio />);
  await screen.findByText(/まだ画面案はありません/);
  fillBrief();
  fireEvent.change(screen.getByLabelText('最初に試す画面'), { target: { value: 'management-dashboard' } });
  fireEvent.click(screen.getByRole('checkbox', { name: '部門別の表' }));
  fireEvent.change(screen.getByLabelText('最初に試す画面'), { target: { value: 'hello-web' } });
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Geminiで画面案を生成' }));
  await screen.findByRole('heading', { name: '生成結果の確認' });
  expect(vi.mocked(aiClient.create).mock.calls[0][0].config).toMatchObject({
    template: 'hello-web', trend: false, departments: false, cash_flow: false,
  });
});

it('pages saved plans instead of rendering an unbounded list', async () => {
  vi.mocked(aiClient.list).mockResolvedValue({ items: Array.from({ length: 21 }, (_, index) => ({
    ...application, id: '10000000-0000-4000-8000-' + String(index).padStart(12, '0'), config: { ...application.config, title: '保存画面' + index },
  })) });
  render(<AiStudio />);
  await screen.findByText('保存画面0');
  const list = within(screen.getByRole('complementary', { name: '保存した画面案' }));
  expect(list.getAllByRole('listitem')).toHaveLength(20);
  fireEvent.click(screen.getByRole('button', { name: '次の20件' }));
  expect(list.getAllByRole('listitem')).toHaveLength(1);
  expect(list.getByRole('button', { name: /保存画面20/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '前の20件' }));
  expect(list.getAllByRole('listitem')).toHaveLength(20);
});

it('keeps the form usable after a list failure and clears that error after successful generation', async () => {
  vi.mocked(aiClient.list).mockRejectedValue(new ApiError('unavailable', 503));
  render(<AiStudio />);
  await screen.findByRole('alert');
  fillBrief();
  fireEvent.click(screen.getByRole('button', { name: 'Geminiで画面案を生成' }));
  await screen.findByRole('heading', { name: '生成結果の確認' });
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it.each([502, 503, 504])('replays the create UUID after ambiguous HTTP %s without another attempt or mock result', async status => {
  vi.mocked(aiClient.create).mockRejectedValueOnce(new ApiError('proxy response uncertain', status, undefined,
    status === 503 ? 'dependency_unavailable' : undefined)).mockResolvedValueOnce(application);
  render(<AiStudio />);
  await screen.findByText(/まだ画面案はありません/);
  fillBrief();
  fireEvent.click(screen.getByRole('button', { name: 'Geminiで画面案を生成' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('入力内容を変えずに再試行');
  expect(aiClient.create).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText('何をできるようにしたいですか？')).toHaveValue(application.brief.purpose);
  expect(screen.queryByTestId('ai-canvas')).not.toBeInTheDocument();
  const first = vi.mocked(aiClient.create).mock.calls[0][0];
  fireEvent.click(screen.getByRole('button', { name: 'Geminiで画面案を生成' }));
  await screen.findByRole('heading', { name: '生成結果の確認' });
  expect(aiClient.create).toHaveBeenCalledTimes(2);
  expect(vi.mocked(aiClient.create).mock.calls[1][0]).toEqual(first);
});

it.each([502, 503, 504])('replays the revision UUID after ambiguous HTTP %s and retains the saved preview until replay resolves', async status => {
  await resume();
  vi.mocked(aiClient.revise).mockRejectedValueOnce(new ApiError('proxy response uncertain', status, undefined,
    status === 503 ? 'dependency_unavailable' : undefined)).mockResolvedValueOnce({
      ...application, revision: 2, config: { ...application.config, color: 'green' },
    });
  fireEvent.change(screen.getByLabelText('追加の指示・修正したいこと'), { target: { value: '緑の配色に変更' } });
  fireEvent.click(screen.getByRole('button', { name: 'Geminiに修正を依頼' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('入力内容を変えずに再試行');
  expect(aiClient.revise).toHaveBeenCalledTimes(1);
  expect(screen.getByTestId('ai-canvas')).toHaveClass('theme-blue');
  expect(screen.getByLabelText('追加の指示・修正したいこと')).toHaveValue('緑の配色に変更');
  const first = vi.mocked(aiClient.revise).mock.calls[0][1];
  fireEvent.click(screen.getByRole('button', { name: 'Geminiに修正を依頼' }));
  await waitFor(() => expect(screen.getByTestId('ai-canvas')).toHaveClass('theme-green'));
  expect(aiClient.revise).toHaveBeenCalledTimes(2);
  expect(vi.mocked(aiClient.revise).mock.calls[1][1]).toEqual(first);
});

it('creates a newly counted revision attempt only after exact terminal ai_generation_failed', async () => {
  await resume();
  vi.mocked(aiClient.revise).mockRejectedValueOnce(new ApiError('generation failed', 503, undefined, 'ai_generation_failed'))
    .mockResolvedValueOnce({ ...application, revision: 2, config: { ...application.config, color: 'green' } });
  fireEvent.change(screen.getByLabelText('追加の指示・修正したいこと'), { target: { value: '緑の配色に変更' } });
  fireEvent.click(screen.getByRole('button', { name: 'Geminiに修正を依頼' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('生成に失敗');
  expect(screen.getByLabelText('追加の指示・修正したいこと')).toHaveValue('緑の配色に変更');
  expect(screen.getByTestId('ai-canvas')).toHaveClass('theme-blue');
  const firstId = vi.mocked(aiClient.revise).mock.calls[0][1].request_id;
  fireEvent.click(screen.getByRole('button', { name: 'Geminiに修正を依頼' }));
  await waitFor(() => expect(screen.getByTestId('ai-canvas')).toHaveClass('theme-green'));
  expect(vi.mocked(aiClient.revise).mock.calls[1][1].request_id).not.toBe(firstId);
  expect(vi.mocked(aiClient.revise).mock.calls[1][1]).toMatchObject({ expected_revision: 1, instruction: '緑の配色に変更' });
});

it('clears the ambiguous create UUID when the user explicitly starts a new plan', async () => {
  vi.mocked(aiClient.create).mockRejectedValueOnce(new ApiError('upstream uncertain', 503, undefined, 'dependency_unavailable'))
    .mockResolvedValueOnce(application);
  render(<AiStudio />);
  await screen.findByText(/まだ画面案はありません/);
  fillBrief();
  fireEvent.click(screen.getByRole('button', { name: 'Geminiで画面案を生成' }));
  await screen.findByRole('alert');
  const firstId = vi.mocked(aiClient.create).mock.calls[0][0].request_id;
  fireEvent.click(screen.getByRole('button', { name: '新しい画面案' }));
  expect(screen.getByLabelText('作りたいアプリ・実現したいこと')).toHaveValue(application.brief.purpose);
  fireEvent.click(screen.getByRole('button', { name: 'つづける' }));
  expect(screen.getByLabelText('アプリ名')).toHaveValue('希望した名前');
  fireEvent.click(screen.getByRole('button', { name: 'Geminiで画面案を生成' }));
  await screen.findByRole('heading', { name: '生成結果の確認' });
  expect(vi.mocked(aiClient.create).mock.calls[1][0].request_id).not.toBe(firstId);
});

it('replays the create UUID after an invalid successful response without rendering a fake generated plan', async () => {
  vi.mocked(aiClient.create).mockRejectedValueOnce(new ApiError('truncated successful response', 201, undefined, 'invalid_response'))
    .mockResolvedValueOnce(application);
  render(<AiStudio />);
  await screen.findByText(/まだ画面案はありません/);
  fillBrief();
  fireEvent.click(screen.getByRole('button', { name: 'Geminiで画面案を生成' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('入力内容を変えずに再試行');
  expect(aiClient.create).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText('何をできるようにしたいですか？')).toHaveValue(application.brief.purpose);
  expect(screen.queryByTestId('ai-canvas')).not.toBeInTheDocument();
  const first = vi.mocked(aiClient.create).mock.calls[0][0];
  fireEvent.click(screen.getByRole('button', { name: 'Geminiで画面案を生成' }));
  await screen.findByRole('heading', { name: '生成結果の確認' });
  expect(vi.mocked(aiClient.create).mock.calls[1][0]).toEqual(first);
});

it('retains the revision UUID, instruction and prior preview after an invalid successful plan', async () => {
  await resume();
  vi.mocked(aiClient.revise).mockRejectedValueOnce(new ApiError('malformed successful plan', 200, undefined, 'invalid_response'))
    .mockResolvedValueOnce({ ...application, revision: 2, config: { ...application.config, color: 'green' } });
  fireEvent.change(screen.getByLabelText('追加の指示・修正したいこと'), { target: { value: '緑の配色に変更' } });
  fireEvent.click(screen.getByRole('button', { name: 'Geminiに修正を依頼' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('入力内容を変えずに再試行');
  expect(aiClient.revise).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText('追加の指示・修正したいこと')).toHaveValue('緑の配色に変更');
  expect(screen.getByTestId('ai-canvas')).toHaveClass('theme-blue');
  const first = vi.mocked(aiClient.revise).mock.calls[0][1];
  fireEvent.click(screen.getByRole('button', { name: 'Geminiに修正を依頼' }));
  await waitFor(() => expect(screen.getByTestId('ai-canvas')).toHaveClass('theme-green'));
  expect(vi.mocked(aiClient.revise).mock.calls[1][1]).toEqual(first);
});

it('keeps the prior saved list and preview when a refresh response fails validation', async () => {
  await resume();
  vi.mocked(aiClient.list).mockRejectedValue(new ApiError('malformed list', 200, undefined, 'invalid_response'));
  fireEvent.click(screen.getByRole('button', { name: '一覧を更新' }));
  await screen.findByRole('alert');
  expect(screen.getByRole('button', { name: /Geminiによる月次レポート/ })).toBeInTheDocument();
  expect(screen.getByTestId('ai-canvas')).toHaveClass('theme-blue');
  expect(aiClient.create).not.toHaveBeenCalled();
  expect(aiClient.revise).not.toHaveBeenCalled();
});
