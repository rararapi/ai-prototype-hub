import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { ApiError, api } from './api';
import type { Action, Operation, Sandbox, SystemInfo, Template } from './api';

const POLL_MS = 1800;
const actionLabels: Record<Action, string> = { start: '起動', stop: '停止', delete: '削除' };
const operationLabels: Record<Operation['status'], string> = {
  queued: '受付済み', running: '処理中', succeeded: '完了', failed: '失敗', superseded: '新しい要求で置き換え',
};
const statusLabels: Record<Sandbox['status'], string> = {
  stopped: '停止中', starting: '起動中', running: 'Ready', stopping: '停止処理中',
  deleting: '削除中', deleted: '削除済み', failed: '失敗',
};

function statusLabel(sandbox: Sandbox, mode: SystemInfo['runtime_mode'] | undefined) {
  return sandbox.status === 'running' && mode === 'mock' ? '模擬起動中' : statusLabels[sandbox.status];
}

function formatDate(value: string | null) {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? '—' : parsed.toLocaleString('ja-JP', { hour12: false });
}

function previewHref(sandbox: Sandbox, mode: SystemInfo['runtime_mode'] | undefined) {
  if (mode !== 'real-kind' || sandbox.status !== 'running' || !sandbox.preview_url) return null;
  try {
    const url = new URL(sandbox.preview_url);
    return ['http:', 'https:'].includes(url.protocol)
      && ['localhost', '127.0.0.1'].includes(url.hostname)
      && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

function ErrorNotice({ error, retry }: { error: Error; retry: () => void }) {
  return <div className="error-notice" role="alert">
    <div><strong>{error instanceof ApiError && error.status >= 400 && error.status < 500 ? '入力・操作を確認してください' : '通信を確認してください'}</strong><p>{error.message}</p>
      {error instanceof ApiError && error.requestId
        ? <small>Request ID: {error.requestId}</small> : null}
    </div>
    <button className="button secondary" onClick={retry}>再試行</button>
  </div>;
}

function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement;
    const root = ref.current;
    const focusable = () => Array.from(root?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input, select, [href], [tabindex="0"]',
    ) ?? []);
    focusable()[0]?.focus();
    const listener = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
      if (event.key !== 'Tab') return;
      const items = focusable();
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', listener);
    return () => {
      document.removeEventListener('keydown', listener);
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, [onClose]);
  return <div className="modal-backdrop"><div className="modal" ref={ref} role="dialog" aria-modal="true" aria-label={title}>
    <div className="modal-heading"><h2>{title}</h2><button className="icon-button" aria-label="閉じる" onClick={onClose}>×</button></div>
    {children}
  </div></div>;
}

function Registration({ templates, busy, onCreate }: {
  templates: Template[]; busy: boolean; onCreate: (name: string, templateId: 'hello-web', ttl: number) => void;
}) {
  const [name, setName] = useState('');
  const [ttl, setTtl] = useState('900');
  const [templateId, setTemplateId] = useState<'hello-web'>('hello-web');
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim() && !busy) onCreate(name.trim(), templateId, Number(ttl));
  };
  return <form onSubmit={submit} className="registration-form">
    <p className="muted">信頼済みテンプレートを登録します。登録後に「起動」を押してください。</p>
    <label htmlFor="app-name">アプリ名</label>
    <input id="app-name" name="name" value={name} onChange={e => setName(e.target.value)} required maxLength={64} placeholder="例: My first app" autoComplete="off" />
    <label htmlFor="template">テンプレート</label>
    <select id="template" value={templateId} onChange={e => setTemplateId(e.target.value as 'hello-web')}>
      {templates.map(template => <option key={template.id} value={template.id}>{template.name}</option>)}
    </select>
    <p className="field-hint">固定のHTTPサンプル。任意のコード・イメージは登録できません。</p>
    <label htmlFor="ttl">自動停止までの時間（秒）</label>
    <input id="ttl" name="ttl_seconds" type="number" min={60} max={3600} step={1} required value={ttl} onChange={e => setTtl(e.target.value)} />
    <p className="field-hint">60〜3600秒。起動が完了してから計測します。</p>
    <button className="button primary full-width" type="submit" disabled={busy || !name.trim() || !templates.length}>
      {busy ? '登録中…' : '登録'}
    </button>
  </form>;
}

export default function App() {
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [sandboxes, setSandboxes] = useState<Sandbox[]>([]);
  const [selected, setSelected] = useState<Sandbox | null>(null);
  const [operation, setOperation] = useState<Operation | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [actionError, setActionError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Sandbox | null>(null);
  const [notice, setNotice] = useState('');
  const selectedId = useRef<string | null>(null);
  const activeOperationId = useRef<string | null>(null);
  const operationCache = useRef<Operation | null>(null);
  const mounted = useRef(false);
  const refreshingRef = useRef(false);
  const refreshSignal = useRef<AbortSignal | undefined>(undefined);
  const refreshSequence = useRef(0);
  const actionBusy = useRef(false);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (refreshingRef.current && !refreshSignal.current?.aborted) return;
    refreshingRef.current = true;
    refreshSignal.current = signal;
    const sequence = ++refreshSequence.current;
    if (mounted.current) setRefreshing(true);
    try {
      const [systemInfo, templateList, list] = await Promise.all([
        api.system(signal), api.templates(signal), api.list(signal),
      ]);
      const requestedId = selectedId.current;
      const detail = requestedId
        ? list.items.find(item => item.id === requestedId) ?? await api.sandbox(requestedId, signal)
        : null;
      const operationId = detail?.active_operation_id ?? activeOperationId.current;
      const cached = operationCache.current;
      const nextOperation = !operationId ? null
        : cached?.id === operationId && !['queued', 'running'].includes(cached.status)
          ? cached : await api.operation(operationId, signal);
      if (!mounted.current || signal?.aborted) return;
      setSystem(systemInfo);
      setTemplates(templateList.items);
      setSandboxes(list.items);
      if (selectedId.current === requestedId) {
        operationCache.current = nextOperation;
        setSelected(detail);
        setOperation(nextOperation);
      }
      setError(null);
    } catch (cause) {
      if (!mounted.current || signal?.aborted) return;
      setError(cause instanceof Error ? cause : new Error('読み込みに失敗しました。'));
    } finally {
      if (sequence === refreshSequence.current) {
        refreshingRef.current = false;
        if (mounted.current && !signal?.aborted) { setInitialLoading(false); setRefreshing(false); }
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    void refresh(controller.signal);
    const interval = window.setInterval(() => { void refresh(controller.signal); }, POLL_MS);
    return () => { mounted.current = false; controller.abort(); window.clearInterval(interval); };
  }, [refresh]);

  const select = (sandbox: Sandbox) => {
    selectedId.current = sandbox.id;
    activeOperationId.current = sandbox.active_operation_id;
    operationCache.current = null;
    setSelected(sandbox);
    setOperation(null);
    setNotice('');
    void refresh();
  };
  const closeCreate = useCallback(() => { if (!actionBusy.current) setShowCreate(false); }, []);
  const closeDelete = useCallback(() => { if (!actionBusy.current) setDeleteTarget(null); }, []);

  const create = async (name: string, templateId: 'hello-web', ttl: number) => {
    if (actionBusy.current) return;
    actionBusy.current = true;
    setBusy(true);
    setActionError(null);
    try {
      const sandbox = await api.create({ name, template_id: templateId, ttl_seconds: ttl });
      if (!mounted.current) return;
      selectedId.current = sandbox.id;
      activeOperationId.current = null;
      operationCache.current = null;
      setSandboxes(items => [sandbox, ...items.filter(item => item.id !== sandbox.id)]);
      setSelected(sandbox);
      setOperation(null);
      setShowCreate(false);
      setNotice('アプリを登録しました。起動すると実行状態を確認できます。');
    } catch (cause) {
      if (mounted.current) setActionError(cause instanceof Error ? cause : new Error('登録に失敗しました。'));
    } finally { actionBusy.current = false; if (mounted.current) setBusy(false); }
  };

  const act = async (sandbox: Sandbox, action: Action) => {
    if (actionBusy.current) return;
    actionBusy.current = true;
    setBusy(true);
    setActionError(null);
    setNotice('');
    try {
      const next = await api.action(sandbox.id, action);
      if (!mounted.current) return;
      activeOperationId.current = next.id;
      operationCache.current = next;
      setOperation(next);
      setDeleteTarget(null);
      setNotice(`${actionLabels[action]}要求を受け付けました。実行状態を確認しています。`);
      await refresh();
    } catch (cause) {
      if (mounted.current) setActionError(cause instanceof Error ? cause : new Error('操作に失敗しました。'));
    } finally { actionBusy.current = false; if (mounted.current) setBusy(false); }
  };

  const running = sandboxes.filter(item => item.status === 'running').length;
  const href = selected ? previewHref(selected, system?.runtime_mode) : null;
  const deleted = selected?.desired_state === 'deleted';
  const displayedError = actionError ?? error;

  return <div className="app-shell">
    <header className="topbar">
      <a className="brand" href="/" aria-label="ProtoHub ホーム"><span className="brand-mark" aria-hidden="true">P</span>ProtoHub<span className="version-tag">LOCAL</span></a>
      <div className="local-principal"><span className="connection-dot" />local-dev<span className="principal-separator">/</span>個人ワークスペース</div>
    </header>
    <main>
      <section className="page-heading">
        <div><p className="eyebrow">YOUR LOCAL WORKSPACE</p><h1>アイデアを、動かそう。</h1><p className="muted">サンプルアプリを登録して、起動・確認・停止まで。</p></div>
        <button className="button primary" onClick={() => setShowCreate(true)} disabled={!system || busy}><span aria-hidden="true">＋</span> サンプルを登録</button>
      </section>

      <div className={`runtime-banner ${system?.runtime_mode === 'real-kind' ? 'real' : ''}`} data-testid="runtime-banner" role="status">
        <span className="runtime-symbol" aria-hidden="true">{system?.runtime_mode === 'real-kind' ? '◉' : '◇'}</span>
        <div><strong>{!system ? error ? 'Runtimeに接続できません' : 'Runtimeを確認中…' : system.runtime_mode === 'mock' ? 'Mock runtime — 実アプリは起動しません' : 'Real runtime — kind上でサンプルを起動します'}</strong>
          <p>{system?.runtime_mode === 'mock' ? 'UI・API・状態遷移の開発用です。模擬起動ではプレビューURLを発行しません。' : 'localhost専用・信頼済みテンプレート限定。外部公開や任意コードの実行には対応していません。'}</p>
        </div>
        <span className="mode-tag">{system?.runtime_mode ?? (error ? 'OFFLINE' : 'CONNECTING')}</span>
      </div>

      {displayedError && <ErrorNotice error={displayedError} retry={() => { setActionError(null); void refresh(); }} />}
      <p className="sr-only" role="status" aria-live="polite">{notice}</p>

      <section className="workspace" aria-label="アプリ管理">
        <aside className="app-list-panel">
          <div className="panel-heading"><h2>アプリ<span className="count">{sandboxes.length}</span></h2>
            <button className="text-button" onClick={() => { void refresh(); }} disabled={refreshing}>更新</button></div>
          <div className="list-summary"><span>{system?.runtime_mode === 'mock' ? '模擬起動' : '実行中'} <b>{running}</b></span><span className="poll-status">{refreshing ? '同期中…' : '自動更新'}</span></div>
          {initialLoading ? <div className="loading-state" role="status"><span className="spinner" />アプリを読み込み中…</div>
            : !system && error ? <div className="empty-list"><h3>アプリ一覧を取得できません</h3><p>上の「再試行」で接続を確認できます。</p></div>
            : !sandboxes.length ? <div className="empty-list"><span className="empty-icon" aria-hidden="true">▧</span><h3>まだアプリがありません</h3><p>最初のサンプルを登録して<br />ワークスペースを始めましょう。</p><button className="button secondary" onClick={() => setShowCreate(true)} disabled={!system}>サンプルを登録</button></div>
              : <ul className="app-list">{sandboxes.map(sandbox => <li key={sandbox.id} data-testid={`sandbox-card-${sandbox.id}`}>
                <button className={`app-row ${selected?.id === sandbox.id ? 'selected' : ''}`} onClick={() => select(sandbox)} aria-label={`${sandbox.name} の詳細`} aria-pressed={selected?.id === sandbox.id} data-testid="sandbox-row" data-sandbox-id={sandbox.id}>
                  <span className="app-avatar" aria-hidden="true">{sandbox.name.slice(0, 1).toUpperCase()}</span>
                  <span className="app-row-copy"><strong>{sandbox.name}</strong><span>Hello Web<span className="row-divider">·</span>{formatDate(sandbox.updated_at)}</span></span>
                  <span className={`status-dot ${sandbox.status}`} title={statusLabel(sandbox, system?.runtime_mode)} aria-label={statusLabel(sandbox, system?.runtime_mode)} />
                </button>
              </li>)}</ul>}
        </aside>

        <article className="detail-panel" aria-label="アプリの詳細" data-testid="sandbox-detail">
          {!selected ? <div className="welcome-state"><div className="welcome-art" aria-hidden="true"><span /><span /><span /></div><p className="eyebrow">A SMALL START. A WORKING IDEA.</p><h2>ここから、ひとつ動かす。</h2><p>左のアプリを選ぶか、サンプルを登録してください。<br />実際の状態を確認しながら、何度でも試せます。</p><div className="lifecycle-guide"><span>登録</span><i>→</i><span>起動</span><i>→</i><span>確認</span><i>→</i><span>停止</span></div></div>
            : <>
              <div className="detail-heading"><div className="detail-title"><span className="app-avatar large" aria-hidden="true">{selected.name.slice(0, 1).toUpperCase()}</span><div><p className="eyebrow">HELLO WEB</p><h2>{selected.name}</h2></div></div><span className={`status-badge ${selected.status}`} data-testid="sandbox-status"><span />{statusLabel(selected, system?.runtime_mode)}</span></div>
              <div className="detail-actions">
                <button className="button primary" onClick={() => { void act(selected, 'start'); }} disabled={busy || deleted || !['stopped', 'failed'].includes(selected.status)}><span aria-hidden="true">▷</span> 起動</button>
                <button className="button secondary" onClick={() => { void act(selected, 'stop'); }} disabled={busy || deleted || !['starting', 'running', 'failed'].includes(selected.status)}><span aria-hidden="true">□</span> 停止</button>
                <button className="button danger-quiet" onClick={() => setDeleteTarget(selected)} disabled={busy || deleted}>削除</button>
                {busy && <span className="action-progress" role="status"><span className="spinner" />送信中…</span>}
              </div>
              {notice && <p className="inline-notice">{notice}</p>}
              {selected.error && <div className="runtime-error" role="alert"><strong>{selected.error.code}</strong><p>{selected.error.message}</p><p>停止・削除で実行リソースを片づけるか、起動を再試行できます。</p></div>}
              <section className="preview-card" aria-label="プレビュー"><div><span className="section-kicker">PREVIEW</span><h3>{href ? 'アプリの準備ができました' : selected.status === 'deleted' ? 'アプリを削除しました' : system?.runtime_mode === 'mock' ? '模擬実行モード' : selected.status === 'starting' ? '起動を確認しています' : '起動すると、ここから開けます'}</h3>
                <p>{href ? '観測済みのサンプルアプリを別タブで開きます。' : system?.runtime_mode === 'mock' ? 'このモードでは実アプリもプレビューURLも作成しません。' : selected.status === 'starting' ? 'Podの準備とHTTP応答をworkerが確認しています。' : '実行リソースの準備が完了するとURLが表示されます。'}</p></div>
                {href ? <a className="button primary" href={href} target="_blank" rel="noopener noreferrer">アプリを開く <span aria-hidden="true">↗</span></a> : <span className="preview-placeholder" aria-hidden="true">↗</span>}
              </section>
              <dl className="metadata-grid"><div><dt>希望する状態</dt><dd>{selected.desired_state}</dd></div><div><dt>自動停止予定</dt><dd data-testid="expires-at">{formatDate(selected.expires_at)}</dd></div><div><dt>テンプレート</dt><dd>{selected.template_id}</dd></div><div><dt>最終更新</dt><dd>{formatDate(selected.updated_at)}</dd></div><div><dt>Generation</dt><dd>{selected.generation}</dd></div><div><dt>登録日時</dt><dd>{formatDate(selected.created_at)}</dd></div><div className="full-metadata"><dt>アプリID</dt><dd className="mono">{selected.id}</dd></div></dl>
              {operation && <section className="operation-card" aria-label="最新の操作" data-testid="operation-status"><div><span className="section-kicker">LATEST OPERATION</span><h3>{actionLabels[operation.action]} · {operationLabels[operation.status]}</h3></div><p>試行 {operation.attempt_count} 回 / 更新 {formatDate(operation.updated_at)}</p>{operation.error && <p role="alert">{operation.error.code}: {operation.error.message}</p>}</section>}
              <p className="detail-footnote">停止は管理レコードを残し、実行を止めます。削除は対象アプリの実行リソースを除去します。</p>
            </>}
        </article>
      </section>
      <footer className="footer"><span>ProtoHub v0<span className="row-divider">·</span>Local development</span><span>信頼済みサンプル専用 / 本番認証・悪性コード隔離は未対応</span></footer>
    </main>
    {showCreate && <Modal title="サンプルアプリを登録" onClose={closeCreate}><Registration templates={templates} busy={busy} onCreate={(name, template, ttl) => { void create(name, template, ttl); }} />{actionError && <p role="alert" className="form-error">{actionError.message}</p>}</Modal>}
    {deleteTarget && <Modal title="アプリを削除" onClose={closeDelete}><p className="delete-copy"><strong>「{deleteTarget.name}」</strong>を削除しますか？</p><p className="muted">このアプリの実行リソースを除去します。他のアプリには影響しません。管理上の削除記録は保持します。</p><div className="modal-actions"><button className="button secondary" onClick={closeDelete} disabled={busy}>キャンセル</button><button className="button danger" onClick={() => { void act(deleteTarget, 'delete'); }} disabled={busy}>{busy ? '削除要求を送信中…' : '削除する'}</button></div>{actionError && <p role="alert" className="form-error">{actionError.message}</p>}</Modal>}
  </div>;
}
