import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError } from './api';
import { aiClient } from './ai-client';
import type { AiApplication, AiBrief, AiConfig, AiCreateRequest, AiReviseRequest } from './ai-client';
import AppCanvas from './AppCanvas';
import './ai-studio.css';

type Busy = 'loading' | 'creating' | 'revising' | 'confirming' | 'deleting' | null;
type FormErrors = Partial<Record<keyof AiBrief | 'title' | 'instruction', string>>;
type Retry<T> = { fingerprint: string; payload: T };
const initialConfig: AiConfig = {
  template: 'management-dashboard', title: '経営管理ダッシュボード',
  subtitle: '売上・費用・利益と予実を、ひと目で。',
  color: 'purple', trend: true, departments: false, cash_flow: false,
};
const emptyBrief: AiBrief = { purpose: '', audience: '', success: '' };
const dates = new Intl.DateTimeFormat('ja-JP', { dateStyle: 'short', timeStyle: 'short' });
const PAGE_SIZE = 20;

function messageFor(error: unknown) {
  if (error instanceof ApiError) {
    if (error.code === 'invalid_response') return '応答内容を確認できませんでした。入力内容を変えずに再試行するか、保存した画面案の一覧を更新してください。';
    if (error.status === 0) return '接続結果を確認できませんでした。同じ内容で再試行できます。';
    if (error.status === 409) return '別の更新が反映されたか、同じ生成処理が進んでいます。最新の画面案を確認してから再試行してください。';
    if (error.status === 429) return '生成回数の上限に達しました。時間をおいて再度お試しください。';
    if (error.status >= 500 && error.status <= 599) {
      if (error.code === 'ai_generation_failed') return 'Geminiの画面案生成に失敗しました。入力内容は残っています。時間をおいて再試行してください。';
      return '生成結果を確認できませんでした。入力内容を変えずに再試行するか、保存した画面案の一覧を更新してください。';
    }
    if (error.status === 404) return 'この画面案は表示できません。一覧を読み直してください。';
    if (error.status === 401) return 'ログインの有効期限が切れました。もう一度ログインしてください。';
  }
  return '処理に失敗しました。入力内容を確認して、もう一度お試しください。';
}
function retainRetry(error: unknown) {
  if (!(error instanceof ApiError) || error.code === 'ai_generation_failed') return false;
  return error.code === 'invalid_response' || error.status === 0 || error.status === 409 || (error.status >= 500 && error.status <= 599);
}
function updatedLabel(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? '更新日時を確認できません' : dates.format(date);
}

export default function AiStudio({ onClose }: { onClose?: () => void }) {
  const [items, setItems] = useState<AiApplication[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState('');
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<AiApplication | null>(null);
  const [config, setConfig] = useState<AiConfig>(() => ({ ...initialConfig }));
  const [brief, setBrief] = useState<AiBrief>(() => ({ ...emptyBrief }));
  const [firstInstruction, setFirstInstruction] = useState('');
  const [revisionInstruction, setRevisionInstruction] = useState('');
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});
  const [notice, setNotice] = useState('');
  const [deleteConfirmation, setDeleteConfirmation] = useState(false);
  const [formEdited, setFormEdited] = useState(false);
  const mounted = useRef(false);
  const active = useRef<AbortController | null>(null);
  const listController = useRef<AbortController | null>(null);
  const listSequence = useRef(0);
  const createRetry = useRef<Retry<AiCreateRequest> | null>(null);
  const reviseRetry = useRef<Retry<AiReviseRequest> | null>(null);
  const form = useRef<HTMLFormElement>(null);
  const reviewHeading = useRef<HTMLHeadingElement>(null);

  const refreshList = useCallback(async () => {
    listController.current?.abort();
    const controller = new AbortController();
    listController.current = controller;
    const sequence = ++listSequence.current;
    setListLoading(true);
    setListError('');
    try {
      const result = await aiClient.list(controller.signal);
      if (mounted.current && !controller.signal.aborted && sequence === listSequence.current) {
        setItems(result.items); setPage(0);
      }
    } catch (cause) {
      if (mounted.current && !controller.signal.aborted && sequence === listSequence.current) setListError(messageFor(cause));
    } finally {
      if (mounted.current && sequence === listSequence.current) setListLoading(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refreshList();
    return () => {
      mounted.current = false;
      listController.current?.abort();
      active.current?.abort();
    };
  }, [refreshList]);
  useEffect(() => { form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(); }, [errors]);
  useEffect(() => { reviewHeading.current?.focus(); }, [selected?.id, selected?.revision, selected?.status]);
  useEffect(() => {
    if (!formEdited || selected) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [formEdited, selected]);

  function upsert(application: AiApplication) {
    ++listSequence.current;
    listController.current?.abort();
    setListLoading(false);
    setListError('');
    setItems(previous => [application, ...previous.filter(item => item.id !== application.id)]);
    setPage(0);
    setSelected(application);
    setDeleteConfirmation(false);
  }

  async function execute<T>(kind: Exclude<Busy, null>, action: (signal: AbortSignal) => Promise<T>,
    success: (value: T) => void, failure?: (cause: unknown) => void) {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(kind);
    setError('');
    setConflict(false);
    setNotice('');
    try {
      const value = await action(controller.signal);
      if (mounted.current && !controller.signal.aborted) success(value);
    } catch (cause) {
      if (mounted.current && !controller.signal.aborted) {
        setError(messageFor(cause));
        setConflict(cause instanceof ApiError && cause.status === 409);
        failure?.(cause);
      }
    } finally {
      if (active.current === controller) {
        active.current = null;
        if (mounted.current) setBusy(null);
      }
    }
  }

  function loadApplication(id: string, keepInstruction = false) {
    reviseRetry.current = null;
    void execute('loading', signal => aiClient.get(id, signal), application => {
      upsert(application);
      if (!keepInstruction) setRevisionInstruction('');
      setErrors({});
    });
  }

  function create(event: FormEvent) {
    event.preventDefault();
    if (active.current) return;
    const nextErrors: FormErrors = {};
    if (!config.title.trim()) nextErrors.title = 'アプリ名を入力してください。';
    for (const key of ['purpose', 'audience', 'success'] as const) {
      if (!brief[key].trim()) nextErrors[key] = '内容を入力してください。';
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    const content = {
      brief: { purpose: brief.purpose.trim(), audience: brief.audience.trim(), success: brief.success.trim() },
      config: { ...config, title: config.title.trim(), subtitle: config.subtitle.trim(),
        trend: config.template === 'management-dashboard' && config.trend,
        departments: config.template === 'management-dashboard' && config.departments,
        cash_flow: config.template === 'management-dashboard' && config.cash_flow },
      instruction: firstInstruction.trim(),
    };
    const fingerprint = JSON.stringify(content);
    if (createRetry.current?.fingerprint !== fingerprint) {
      createRetry.current = { fingerprint, payload: { ...content, request_id: crypto.randomUUID() } };
    }
    const payload = createRetry.current.payload;
    void execute('creating', signal => aiClient.create(payload, signal), application => {
      createRetry.current = null;
      upsert(application);
      setFormEdited(false);
      setNotice('Geminiが画面案を生成しました。内容を確認してください。');
    }, cause => { if (!retainRetry(cause)) createRetry.current = null; });
  }

  function revise(event: FormEvent) {
    event.preventDefault();
    if (!selected || active.current) return;
    if (!revisionInstruction.trim()) { setErrors({ instruction: '修正したい内容を入力してください。' }); return; }
    setErrors({});
    const content = { expected_revision: selected.revision, instruction: revisionInstruction.trim() };
    const fingerprint = selected.id + JSON.stringify(content);
    if (reviseRetry.current?.fingerprint !== fingerprint) {
      reviseRetry.current = { fingerprint, payload: { ...content, request_id: crypto.randomUUID() } };
    }
    const payload = reviseRetry.current.payload;
    void execute('revising', signal => aiClient.revise(selected.id, payload, signal), application => {
      reviseRetry.current = null;
      upsert(application);
      setRevisionInstruction('');
      setNotice('Geminiが画面案を修正しました。新しい内容を確認してください。');
    }, cause => { if (!retainRetry(cause)) reviseRetry.current = null; });
  }

  function confirm() {
    if (!selected) return;
    void execute('confirming', signal => aiClient.confirm(selected.id, selected.revision, signal), application => {
      upsert(application);
      setNotice('画面案を確認済みとして保存しました。');
    });
  }

  function remove() {
    if (!selected) return;
    const id = selected.id;
    void execute('deleting', signal => aiClient.remove(id, signal), () => {
      ++listSequence.current;
      listController.current?.abort();
      setListLoading(false);
      setItems(previous => previous.filter(item => item.id !== id));
      setSelected(null);
      setDeleteConfirmation(false);
      setPage(0);
      setNotice('画面案を削除しました。');
    });
  }

  function newApplication() {
    if (active.current) return;
    setSelected(null);
    setError('');
    setConflict(false);
    setNotice('');
    setErrors({});
    setDeleteConfirmation(false);
    createRetry.current = null;
    reviseRetry.current = null;
  }

  function changeConfig<K extends keyof AiConfig>(key: K, value: AiConfig[K]) {
    setConfig(previous => ({ ...previous, [key]: value }));
    setFormEdited(true);
  }

  const briefField = (key: keyof AiBrief, label: string, placeholder: string) => <div className="ai-field">
    <label htmlFor={'ai-' + key}>{label}</label>
    <textarea id={'ai-' + key} name={key} maxLength={300} rows={2} autoComplete="off"
      value={brief[key]} onChange={event => { setBrief(previous => ({ ...previous, [key]: event.target.value })); setFormEdited(true); }}
      disabled={Boolean(busy)} aria-invalid={Boolean(errors[key])}
      aria-describedby={errors[key] ? 'ai-' + key + '-error' : undefined} placeholder={placeholder} />
    {errors[key] && <p className="ai-field-error" id={'ai-' + key + '-error'}>{errors[key]}</p>}
  </div>;

  return <section className="ai-studio" aria-label="Geminiアプリ作成">
    <p className="ai-intro">目的から画面案を作り、確認して保存します。保存した画面案は後から再開できます。</p>
    <p className="ai-service-note">入力内容はサーバーからGeminiへ送信されます。生成回数には上限があります。画面見本には架空のデータを使います。</p>
    <div className="ai-studio-layout">
      <aside className="ai-saved" aria-label="保存した画面案">
        <div className="ai-saved-heading"><h3>保存した画面案</h3>
          <button type="button" className="text-button" onClick={() => { void refreshList(); }} disabled={Boolean(busy) || listLoading}>一覧を更新</button></div>
        <button type="button" className="button secondary ai-new" onClick={newApplication} disabled={Boolean(busy)}>新しい画面案</button>
        {listLoading && <p role="status" className="field-hint">画面案を読み込み中…</p>}
        {listError && <p role="alert" className="ai-list-error">{listError}</p>}
        {!listLoading && !listError && !items.length && <p className="ai-empty">まだ画面案はありません。目的を入力してGeminiで生成してください。</p>}
        <ul className="ai-saved-list">{items.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).map(item => <li key={item.id}>
          <button type="button" aria-current={selected?.id === item.id ? 'true' : undefined}
            onClick={() => loadApplication(item.id)} disabled={Boolean(busy)}>
            <strong>{item.config.title}</strong><span>{item.status === 'ready' ? '確認済み' : '確認待ち'} · v{item.revision}</span>
            <small>{updatedLabel(item.updated_at)}</small>
          </button>
        </li>)}</ul>
        {items.length > PAGE_SIZE && <div className="ai-pagination" aria-label="保存した画面案のページ">
          <button type="button" className="text-button" disabled={Boolean(busy) || page === 0} onClick={() => setPage(page - 1)}>前の20件</button>
          <span>{page + 1} / {Math.ceil(items.length / PAGE_SIZE)}</span>
          <button type="button" className="text-button" disabled={Boolean(busy) || (page + 1) * PAGE_SIZE >= items.length} onClick={() => setPage(page + 1)}>次の20件</button>
        </div>}
      </aside>
      <div className="ai-workspace">
        {notice && <p role="status" className="ai-notice">{notice}</p>}
        {error && <div className="ai-action-error"><p role="alert">{error}</p>
          {conflict && selected && <button type="button" className="button secondary" disabled={Boolean(busy)} onClick={() => loadApplication(selected.id, true)}>最新の画面案を読み直す</button>}</div>}
        {busy && <p role="status" className="ai-progress">{{
          loading: '保存した画面案を読み込み中…', creating: 'Geminiで画面案を生成中…',
          revising: 'Geminiで修正案を生成中…', confirming: '確認内容を保存中…', deleting: '画面案を削除中…',
        }[busy]}</p>}
        {(busy === 'creating' || busy === 'revising') && <p className="field-hint">閉じた後もサーバー側の生成が完了する場合があります。再開時に一覧を確認してください。</p>}
        {!selected ? <form className="registration-form ai-create" onSubmit={create} ref={form} noValidate>
          <h3>作りたい画面を教えてください</h3>
          <p className="field-hint">技術構成は標準のまま、目的と画面の内容を決めます。</p>
          <label htmlFor="ai-title">アプリ名</label>
          <input id="ai-title" name="title" maxLength={64} autoComplete="off" value={config.title}
            onChange={event => changeConfig('title', event.target.value)} disabled={Boolean(busy)}
            aria-invalid={Boolean(errors.title)} aria-describedby={errors.title ? 'ai-title-error' : undefined} />
          {errors.title && <p className="ai-field-error" id="ai-title-error">{errors.title}</p>}
          {briefField('purpose', '何をできるようにしたいですか？', '例: 毎月の予実を確認して、対応が必要な部門を見つけたい…')}
          {briefField('audience', '誰が使いますか？', '例: 月次会議に参加する担当者…')}
          {briefField('success', '画面見本で、どんなことを確かめたいですか？', '例: 会議で部門ごとの差を見つけやすいか確かめたい…')}
          <label htmlFor="ai-template">最初に試す画面</label>
          <select id="ai-template" name="template" value={config.template} disabled={Boolean(busy)} onChange={event => {
            const template = event.target.value as AiConfig['template'];
            setConfig(previous => ({ ...previous, template, trend: template === 'management-dashboard',
              departments: false, cash_flow: false }));
            setFormEdited(true);
          }}><option value="management-dashboard">経営管理ダッシュボード</option><option value="hello-web">案内用のWebページ</option></select>
          <label htmlFor="ai-subtitle">画面の説明文</label>
          <textarea id="ai-subtitle" name="subtitle" autoComplete="off" maxLength={160} rows={2}
            value={config.subtitle} onChange={event => changeConfig('subtitle', event.target.value)} disabled={Boolean(busy)} />
          {config.template === 'management-dashboard' && <fieldset className="ai-options"><legend>最初に入れたい表示</legend>
            {([['trend', '売上・利益の推移グラフ'], ['departments', '部門別の表'], ['cash_flow', 'キャッシュフローカード']] as const).map(([key, label]) =>
              <label key={key}><input type="checkbox" name={key} checked={config[key]} onChange={event => changeConfig(key, event.target.checked)} disabled={Boolean(busy)} />{label}</label>)}
          </fieldset>}
          <fieldset className="ai-options ai-colors"><legend>希望する配色</legend>
            {([['purple', '紫'], ['blue', '青'], ['green', '緑']] as const).map(([value, label]) =>
              <label key={value}><input type="radio" name="color" checked={config.color === value} onChange={() => changeConfig('color', value)} disabled={Boolean(busy)} />{label}</label>)}
          </fieldset>
          <label htmlFor="ai-first-instruction">最初の追加要望（任意）</label>
          <textarea id="ai-first-instruction" name="initial_instruction" maxLength={1000} rows={2} autoComplete="off"
            value={firstInstruction} onChange={event => { setFirstInstruction(event.target.value); setFormEdited(true); }}
            placeholder="例: 部門ごとに比較しやすいタイトルと説明文にして…" disabled={Boolean(busy)} />
          <p className="field-hint">目的・入力した内容をGeminiに送信し、対応する表示項目の範囲で画面案を作ります。</p>
          <button className="button primary full-width" type="submit" disabled={Boolean(busy)}>{busy === 'creating' ? 'Geminiで生成中…' : 'Geminiで画面案を生成'}</button>
        </form> : <>
          <div className="ai-result-heading"><h3 ref={reviewHeading} tabIndex={-1}>{selected.status === 'ready' ? '確認済みの画面案' : '生成結果の確認'}</h3>
            <span className="ai-plan-status">{selected.status === 'ready' ? '確認済み' : '確認待ち'} · v{selected.revision}</span></div>
          <p className="ai-model">生成モデル: <span translate="no">{selected.model}</span></p>
          <p className="ai-result-summary">{selected.summary}</p>
          <dl className="ai-facts">
            <div><dt>画面名</dt><dd>{selected.config.title}</dd></div>
            <div><dt>画面の説明文</dt><dd>{selected.config.subtitle || '説明文なし'}</dd></div>
            <div><dt>目的</dt><dd>{selected.brief.purpose}</dd></div>
            <div><dt>使う人</dt><dd>{selected.brief.audience}</dd></div>
            <div><dt>確かめたいこと</dt><dd>{selected.brief.success}</dd></div>
            <div><dt>表示内容</dt><dd>{[
              selected.config.template === 'management-dashboard' ? '経営管理ダッシュボード' : '案内用のWebページ',
              selected.config.trend ? '推移グラフ' : '', selected.config.departments ? '部門別の表' : '',
              selected.config.cash_flow ? 'キャッシュフロー' : '',
              { purple: '紫', blue: '青', green: '緑' }[selected.config.color] + 'の配色',
            ].filter(Boolean).join('、')}</dd></div>
          </dl>
          <p className="field-hint">生成結果と下書きは保存されています。表示内容を確認して確定するか、追加の修正を依頼してください。</p>
          <div className="ai-confirm-actions">
            <button type="button" className="button primary" onClick={confirm} disabled={Boolean(busy) || selected.status === 'ready'}>{busy === 'confirming' ? '確認内容を保存中…' : selected.status === 'ready' ? '確認済みとして保存済み' : 'この内容で確定'}</button>
            <button type="button" className="text-button ai-delete" onClick={() => setDeleteConfirmation(true)} disabled={Boolean(busy)}>画面案を削除</button>
          </div>
          {deleteConfirmation && <section className="ai-delete-confirmation" aria-label="削除の確認">
            <p>「{selected.config.title}」を削除しますか？保存した画面案を一覧から削除します。</p>
            <div className="ai-confirm-actions"><button type="button" className="button danger" disabled={Boolean(busy)} onClick={remove}>削除する</button>
              <button type="button" className="button secondary" disabled={Boolean(busy)} onClick={() => setDeleteConfirmation(false)}>削除をやめる</button></div>
          </section>}
          <div className="ai-preview"><p className="ai-section-label">画面見本</p><AppCanvas config={selected.config} /></div>
          <form className="ai-revise" onSubmit={revise} ref={form} noValidate>
            <label htmlFor="ai-revision-instruction">追加の指示・修正したいこと</label>
            <textarea id="ai-revision-instruction" name="instruction" maxLength={1000} rows={3} autoComplete="off"
              value={revisionInstruction} onChange={event => setRevisionInstruction(event.target.value)} disabled={Boolean(busy)}
              aria-invalid={Boolean(errors.instruction)} aria-describedby={errors.instruction ? 'ai-instruction-error' : undefined}
              placeholder="例: 部門別の表を追加して、説明文を短くして…" />
            {errors.instruction && <p id="ai-instruction-error" className="ai-field-error">{errors.instruction}</p>}
            <div className="ai-revise-actions"><small>修正内容をGeminiに送信します。最大1,000文字。</small>
              <button className="button primary" type="submit" disabled={Boolean(busy)}>{busy === 'revising' ? 'Geminiで修正中…' : 'Geminiに修正を依頼'}</button></div>
          </form>
          <p className="field-hint">これは保存した画面設定のプレビューです。コード生成、実データ接続、アプリの実行・公開は行いません。</p>
        </>}
      </div>
    </div>
    {onClose && <div className="ai-studio-footer"><button type="button" className="button secondary" onClick={onClose}>作成画面を閉じる</button></div>}
  </section>;
}
