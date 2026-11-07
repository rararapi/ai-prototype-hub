import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import type { PreviewPlan } from './app-brief';
import GooglePreview, { registeredPreviewURL } from './GooglePreview';
import { IS_DEMO } from './demo-mode';
import { ApiError, api, sessionStore, SESSION_EXPIRED_EVENT } from './api';
import type { Action, LoginSession, Operation, Sandbox, SystemInfo, Template, TemplateId } from './api';

const GoogleLogin = lazy(() => import('./GoogleLogin'));
const AiStudio = import.meta.env.VITE_DEMO_MODE !== 'true' ? lazy(() => import('./AiStudio')) : null;
const DemoBuilder = import.meta.env.VITE_DEMO_MODE === 'true' ? lazy(() => import('./DemoBuilder')) : null;
const DemoCreation = import.meta.env.VITE_DEMO_MODE === 'true' ? lazy(() => import('./DemoCreation')) : null;
const DemoShareEditor = import.meta.env.VITE_DEMO_MODE === 'true' ? lazy(() => import('./DemoShareEditor')) : null;
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

function Modal({ title, children, onClose, wide = false }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement;
    const root = ref.current;
    const focusable = () => Array.from(root?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [href], [tabindex="0"]',
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
  return <div className="modal-backdrop"><div className={wide ? 'modal modal-wide' : 'modal'} ref={ref} role="dialog" aria-modal="true" aria-label={title}>
    <div className="modal-heading"><h2>{title}</h2><button className="icon-button" aria-label="閉じる" onClick={onClose}>×</button></div>
    {children}
  </div></div>;
}

function Registration({ templates, busy, onCreate }: {
  templates: Template[]; busy: boolean; onCreate: (name: string, templateId: TemplateId, ttl: number) => void;
}) {
  const [name, setName] = useState('');
  const [ttl, setTtl] = useState('900');
  const [templateId, setTemplateId] = useState<TemplateId>('hello-web');
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim() && !busy) onCreate(name.trim(), templateId, Number(ttl));
  };
  return <form onSubmit={submit} className="registration-form">
    <p className="muted">信頼済みテンプレートを登録します。登録後に「起動」を押してください。</p>
    <label htmlFor="app-name">アプリ名</label>
    <input id="app-name" name="name" value={name} onChange={e => setName(e.target.value)} required maxLength={64} placeholder="例: My first app" autoComplete="off" />
    <label htmlFor="template">テンプレート</label>
    <select id="template" value={templateId} onChange={e => setTemplateId(e.target.value as TemplateId)}>
      {templates.map(template => <option key={template.id} value={template.id}>{template.name}</option>)}
    </select>
    <p className="field-hint">{IS_DEMO ? 'Hello Webと経営管理の固定テンプレートを選べます。' : '固定のHTTPサンプル。任意のコード・イメージは登録できません。'}</p>
    <label htmlFor="ttl">自動停止までの時間（秒）</label>
    <input id="ttl" name="ttl_seconds" type="number" min={60} max={3600} step={1} required value={ttl} onChange={e => setTtl(e.target.value)} />
    <p className="field-hint">60〜3600秒。起動が完了してから計測します。</p>
    <button className="button primary full-width" type="submit" disabled={busy || !name.trim() || !templates.length}>
      {busy ? '登録中…' : '登録'}
    </button>
  </form>;
}

function Login({ system, busy, error, onLogin }: {
  system: SystemInfo | null; busy: boolean; error: string; onLogin: (input: string) => void;
}) {
  const [email, setEmail] = useState('');
  if (IS_DEMO) return <div className="app-shell">
    <a className="skip-link" href="#main-content">メインコンテンツへ</a>
    <header className="topbar"><a className="brand" href={import.meta.env.BASE_URL} aria-label="ProtoHub ホーム"><span className="brand-mark" aria-hidden="true">P</span>ProtoHub<span className="version-tag">DEMO</span></a></header>
    <main id="main-content" className="login-page"><section className="login-panel" aria-labelledby="demo-heading">
      <h1 id="demo-heading">ProtoHub 操作デモ</h1>
      <p className="muted">AIへの指示でアプリを作り、修正しながら試せます。Hello Webと経営管理テンプレートを用意しています。</p>
      <p>すべてブラウザ内の模擬動作です。実アプリやLLMには接続せず、API利用料はかかりません。</p>
      <p className="field-hint">メール入力は不要です。作成画面のデータは再読み込みでリセットされます。公開デモには実際の個人情報や業務データを入力しないでください。</p>
      <button className="button primary full-width" onClick={() => onLogin('demo@example.test')} disabled={busy}>{busy ? '準備中…' : '操作デモを始める'}</button>
      {error && <p role="alert" className="form-error">{error}</p>}
    </section></main>
  </div>;
  const google = system?.auth_mode === 'google';
  return <div className="app-shell">
    <header className="topbar"><a className="brand" href={import.meta.env.BASE_URL} aria-label="ProtoHub ホーム"><span className="brand-mark" aria-hidden="true">P</span>ProtoHub{!google && <span className="version-tag">LOCAL</span>}</a></header>
    <main id="main-content" className="login-page"><section className="login-panel" aria-labelledby="login-heading">
      <h1 id="login-heading">{google ? 'ProtoHub にログイン' : '開発用ログイン'}</h1>
      {google ? system?.google_client_id
        ? <Suspense fallback={<p role="status">ログイン画面を準備中…</p>}><GoogleLogin clientId={system.google_client_id} busy={busy} onCode={onLogin} /></Suspense>
        : <p role="alert">Google ログインの設定を確認してください。</p>
        : <>
      <p className="muted">メールアドレスを入力して、自分のアプリと共有されたアプリを開きます。</p>
      <p className="field-hint">ローカル・開発環境専用です。メールの本人確認は行いません。</p>
      {system?.auth_mode !== 'local-dev' ? <p role="status">この環境では開発用ログインを利用できません。</p> : <form className="registration-form" onSubmit={event => { event.preventDefault(); if (!busy) onLogin(email.trim()); }}>
        <label htmlFor="login-email">メールアドレス</label>
        <input id="login-email" name="email" type="email" autoComplete="username" spellCheck={false} required maxLength={254} placeholder="例: developer@example.test…" value={email} onChange={event => setEmail(event.target.value)} aria-describedby={error ? 'login-error' : undefined} aria-invalid={error ? true : undefined} />
        <button className="button primary full-width" type="submit" disabled={busy}>{busy ? 'ログイン中…' : '開発用ログイン'}</button>
      </form>}</>}
      {error && <p id="login-error" role="alert" className="form-error">{error}</p>}
    </section></main>
  </div>;
}

export default function App() {
  const [session, setSession] = useState<LoginSession | null>(() => sessionStore.get());
  const [checking, setChecking] = useState(() => sessionStore.get() !== null);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [systemFailed, setSystemFailed] = useState(false);
  const [systemAttempt, setSystemAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const authGeneration = useRef(0);
  const loginController = useRef<AbortController | null>(null);
  const invalidate = useCallback((message = '') => {
    authGeneration.current += 1;
    loginController.current?.abort();
    sessionStore.clear();
    setSession(null);
    setChecking(false);
    setBusy(false);
    setError(message);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void api.system(controller.signal).then(info => {
      if (!controller.signal.aborted) { setSystem(info); setSystemFailed(false); }
    }).catch(() => { if (!controller.signal.aborted) setSystemFailed(true); });
    return () => controller.abort();
  }, [systemAttempt]);

  useEffect(() => {
    const controller = new AbortController();
    const stored = sessionStore.get();
    const generation = authGeneration.current;
    if (stored) {
      void api.me(controller.signal).then(principal => {
        if (controller.signal.aborted || generation !== authGeneration.current) return;
        if (principal.email !== stored.email) invalidate('再度ログインしてください。');
        else setChecking(false);
      }).catch(cause => {
        if (!controller.signal.aborted && generation === authGeneration.current) invalidate(cause instanceof Error ? cause.message : '再度ログインしてください。');
      });
    }
    const expired = (event: Event) => {
      if ((event as CustomEvent<string>).detail === sessionStore.get()?.token) invalidate('ログインの有効期限が切れました。再度ログインしてください。');
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, expired);
    return () => {
      controller.abort();
      loginController.current?.abort();
      authGeneration.current += 1;
      window.removeEventListener(SESSION_EXPIRED_EVENT, expired);
    };
  }, [invalidate]);

  useEffect(() => {
    if (!session) return;
    const expires = Date.parse(session.expires_at) - Date.now();
    const timer = window.setTimeout(() => invalidate('ログインの有効期限が切れました。再度ログインしてください。'), Math.max(0, Math.min(expires, 2_147_483_647)));
    return () => window.clearTimeout(timer);
  }, [session, invalidate]);

  const login = async (input: string) => {
    if (busy || (!IS_DEMO && !['google', 'local-dev'].includes(system?.auth_mode ?? ''))) return;
    const generation = ++authGeneration.current;
    const controller = new AbortController();
    loginController.current = controller;
    setBusy(true);
    setError('');
    try {
      const next = system?.auth_mode === 'google'
        ? await api.googleLogin(input, controller.signal) : await api.login(input, controller.signal);
      if (controller.signal.aborted || generation !== authGeneration.current) return;
      sessionStore.set(next);
      setSession(next);
      setChecking(false);
    } catch (cause) {
      if (!controller.signal.aborted && generation === authGeneration.current) {
        const denied = system?.auth_mode === 'google' && cause instanceof ApiError && cause.status === 403;
        setError(denied ? 'この Google アカウントでログインできません。管理者に登録状況を確認してください。'
          : cause instanceof Error ? cause.message : 'ログインに失敗しました。');
      }
    } finally {
      if (!controller.signal.aborted && generation === authGeneration.current) setBusy(false);
    }
  };
  const logout = () => {
    const pending = api.logout();
    invalidate();
    const generation = authGeneration.current;
    void pending.catch(() => {
      if (generation === authGeneration.current) setError('このタブからログアウトしました。サーバーに接続できず、セッションの失効は有効期限まで保留されています。');
    });
  };

  if (!IS_DEMO && !system && systemFailed) return <main className="login-page"><section className="login-panel">
    <p role="alert">ログイン設定を取得できませんでした。</p>
    <button className="button secondary" onClick={() => { setSystemFailed(false); setSystemAttempt(n => n + 1); }}>再試行</button>
  </section></main>;
  if (checking || (!IS_DEMO && !system)) return <main className="loading-state" role="status">アプリを読み込み中…</main>;
  return session ? <Workspace key={session.token} session={session} onLogout={logout} />
    : <Login system={system} busy={busy} error={error} onLogin={input => { void login(input); }} />;
}

function ShareEditor({ sandbox, signal, onSaved, onClose }: {
  sandbox: Sandbox; signal: AbortSignal; onSaved: () => void; onClose: () => void;
}) {
  const [emails, setEmails] = useState('');
  const [savedEmails, setSavedEmails] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const savingRef = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal.addEventListener('abort', abort);
    void api.shares(sandbox.id, controller.signal).then(result => {
      if (!controller.signal.aborted) { const current = (result.emails ?? []).join('\n'); setEmails(current); setSavedEmails(current); setLoading(false); }
    }).catch(cause => {
      if (!controller.signal.aborted) { setError(cause instanceof Error ? cause.message : '共有設定を取得できません。'); setLoadFailed(true); setLoading(false); }
    });
    return () => { controller.abort(); signal.removeEventListener('abort', abort); };
  }, [sandbox.id, signal]);
  useEffect(() => {
    if (emails === savedEmails || loading || saving) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [emails, savedEmails, loading, saving]);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (savingRef.current || loading || loadFailed || signal.aborted) return;
    const recipients = emails.split(/[\n,]+/).map(email => email.trim()).filter(Boolean);
    if (recipients.length > 100) { setError('共有先は100件以内で入力してください。'); return; }
    savingRef.current = true;
    setSaving(true);
    setError('');
    try {
      await api.setShares(sandbox.id, recipients, signal);
      if (!signal.aborted) onSaved();
    } catch (cause) {
      if (!signal.aborted) setError(cause instanceof Error ? cause.message : '共有設定を保存できません。');
    } finally { savingRef.current = false; if (!signal.aborted) setSaving(false); }
  };
  const close = useCallback(() => { if (!savingRef.current) onClose(); }, [onClose]);
  return <Modal title="アプリの共有" onClose={close}>
    <form className="registration-form" onSubmit={event => { void save(event); }}>
      <p className="muted">「{sandbox.name}」を共有します。共有先は閲覧のみ可能です。起動・停止・削除は所有者が行います。</p>
      <label htmlFor="share-emails">共有先のメールアドレス</label>
      <textarea id="share-emails" name="emails" autoComplete="off" spellCheck={false} rows={5} value={emails} onChange={event => setEmails(event.target.value)} disabled={loading || saving} placeholder="reader@example.test…" aria-describedby="share-help" aria-invalid={error ? true : undefined} />
      <p id="share-help" className="field-hint">1行に1件、100件まで。削除したメールアドレスへの共有は解除されます。</p>
      {loading && <p role="status">共有設定を読み込み中…</p>}
      {error && <p role="alert" className="form-error">{error}</p>}
      <div className="modal-actions"><button className="button secondary" type="button" onClick={onClose} disabled={saving}>キャンセル</button><button className="button primary" type="submit" disabled={loading || loadFailed || saving}>{saving ? '保存中…' : '共有を保存'}</button></div>
    </form>
  </Modal>;
}

function Workspace({ session, onLogout }: { session: LoginSession; onLogout: () => void }) {
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
  const [showAiCreate, setShowAiCreate] = useState(false);
  const [showAiStudio, setShowAiStudio] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Sandbox | null>(null);
  const [notice, setNotice] = useState('');
  const [shareTarget, setShareTarget] = useState<Sandbox | null>(null);
  const [previewTarget, setPreviewTarget] = useState<string | null>(null);
  const closePreview = useCallback(() => setPreviewTarget(null), []);
  const closeAiStudio = useCallback(() => setShowAiStudio(false), []);
  const lifetime = useRef(new AbortController());
  const selectedId = useRef<string | null>(null);
  const activeOperationId = useRef<string | null>(null);
  const operationCache = useRef<Operation | null>(null);
  const mounted = useRef(false);
  const refreshingRef = useRef(false);
  const refreshSignal = useRef<AbortSignal | undefined>(undefined);
  const refreshSequence = useRef(0);
  const actionBusy = useRef(false);

  const refresh = useCallback(async (signal: AbortSignal = lifetime.current.signal) => {
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
        ? list.items.find(item => item.id === requestedId) ?? await api.sandbox(requestedId, signal).catch(cause => {
          if (cause instanceof ApiError && cause.status === 404) return null;
          throw cause;
        })
        : null;
      const operationId = detail ? detail.active_operation_id ?? activeOperationId.current : null;
      const cached = operationCache.current;
      const nextOperation = !operationId ? null
        : cached?.id === operationId && !['queued', 'running'].includes(cached.status)
          ? cached : await api.operation(operationId, signal);
      if (!mounted.current || signal?.aborted) return;
      setSystem(systemInfo);
      setTemplates(templateList.items);
      setSandboxes(list.items);
      if (selectedId.current === requestedId) {
        if (requestedId && !detail) {
          selectedId.current = null;
          activeOperationId.current = null;
        }
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
    const controller = lifetime.current.signal.aborted ? new AbortController() : lifetime.current;
    lifetime.current = controller;
    void refresh(controller.signal);
    const interval = window.setInterval(() => { void refresh(controller.signal); }, POLL_MS);
    return () => { mounted.current = false; controller.abort(); window.clearInterval(interval); };
  }, [refresh]);

  const select = (sandbox: Sandbox) => {
    setPreviewTarget(null);
    selectedId.current = sandbox.id;
    activeOperationId.current = sandbox.active_operation_id;
    operationCache.current = null;
    setSelected(sandbox);
    setOperation(null);
    setNotice('');
    void refresh();
  };
  const closeAiCreate = useCallback(() => { if (!actionBusy.current) setShowAiCreate(false); }, []);
  const closeCreate = useCallback(() => { if (!actionBusy.current) setShowCreate(false); }, []);
  const closeDelete = useCallback(() => { if (!actionBusy.current) setDeleteTarget(null); }, []);

  const create = async (name: string, templateId: TemplateId, ttl: number, instruction?: string, plan?: PreviewPlan) => {
    if (actionBusy.current) return;
    actionBusy.current = true;
    setBusy(true);
    setActionError(null);
    try {
      const sandbox = await api.create({ name, template_id: templateId, ttl_seconds: ttl }, lifetime.current.signal);
      if (!mounted.current) return;
      if (import.meta.env.VITE_DEMO_MODE === 'true' && instruction !== undefined) {
        const { seedDraft } = await import('./demo-builder');
        if (!mounted.current || lifetime.current.signal.aborted) return;
        seedDraft(sandbox.id, templateId, instruction, plan);
      }
      selectedId.current = sandbox.id;
      activeOperationId.current = null;
      operationCache.current = null;
      setSandboxes(items => [sandbox, ...items.filter(item => item.id !== sandbox.id)]);
      setSelected(sandbox);
      setOperation(null);
      setShowCreate(false);
      if (import.meta.env.VITE_DEMO_MODE === 'true' && instruction !== undefined) {
        const next = await api.action(sandbox.id, 'start', lifetime.current.signal);
        if (!mounted.current) return;
        activeOperationId.current = next.id;
        operationCache.current = next;
        setOperation(next);
        setShowAiCreate(false);
        setNotice('モックAIで画面見本を作成しました。追加の指示で内容を変えられます。');
        await refresh();
      } else setNotice('アプリを登録しました。起動すると実行状態を確認できます。');
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
      const next = await api.action(sandbox.id, action, lifetime.current.signal);
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
  const google = system?.auth_mode === 'google';
  const href = !google && selected ? previewHref(selected, system?.runtime_mode) : null;
  const protectedPreview = google && selected?.template_id === 'hello-web' &&
    selected.status === 'running' && selected.desired_state === 'running' && selected.preview_url &&
    system.runtime_mode === 'real-kind' ? registeredPreviewURL(system.preview_origin, selected.id) : null;
  const deleted = selected?.desired_state === 'deleted';
  const owned = selected?.owner_email === session.email;
  const closeShares = useCallback(() => setShareTarget(null), []);
  const displayedError = actionError ?? error;
  const liveShareTarget = shareTarget ? selected?.id === shareTarget.id ? selected
    : sandboxes.find(item => item.id === shareTarget.id) ?? { ...shareTarget, desired_state: 'deleted' as const, status: 'deleted' as const } : null;

  return <div className="app-shell">
    <a className="skip-link" href="#main-content">メインコンテンツへ</a>
    <header className="topbar">
      <a className="brand" href={import.meta.env.BASE_URL} aria-label="ProtoHub ホーム"><span className="brand-mark" aria-hidden="true">P</span>ProtoHub{!google && <span className="version-tag">{IS_DEMO ? 'DEMO' : 'LOCAL'}</span>}</a>
      <div className="local-principal"><span className="connection-dot" aria-hidden="true" /><span className="principal-email">{session.email}</span><button className="text-button" onClick={onLogout}>{IS_DEMO ? 'デモを終了' : 'ログアウト'}</button></div>
    </header>
    <main id="main-content">
      <section className="page-heading">
        <div>{!google && <p className="eyebrow">YOUR LOCAL WORKSPACE</p>}<h1>アイデアを、動かそう。</h1><p className="muted">{IS_DEMO ? 'AIに伝えて作り、指摘して直す。画面が育つ流れを体験できます。' : '自分のアプリと、共有されたアプリを管理します。'}</p></div>
        <div className="heading-actions"><button className={IS_DEMO ? 'button secondary' : 'button primary'} onClick={() => setShowCreate(true)} disabled={!system || busy}><span aria-hidden="true">＋</span> サンプルを登録</button>
          {!IS_DEMO && AiStudio && system?.ai_enabled && <button className="button primary" onClick={() => setShowAiStudio(true)}>Geminiでアプリを作る</button>}
          {DemoCreation && <button className="button primary" onClick={() => setShowAiCreate(true)} disabled={!system || busy}>AIでアプリを作る</button>}</div>
      </section>

      <div className={`runtime-banner ${system?.runtime_mode === 'real-kind' ? 'real' : ''}`} data-testid="runtime-banner" role="status">
        <span className="runtime-symbol" aria-hidden="true">{system?.runtime_mode === 'real-kind' ? '◉' : '◇'}</span>
        <div><strong>{IS_DEMO ? '操作デモ — 実アプリは起動しません' : !system ? error ? 'Runtimeに接続できません' : 'Runtimeを確認中…' : system.runtime_mode === 'mock' ? 'Mock runtime — 実アプリは起動しません' : google ? 'Real runtime — Kubernetes でサンプルを起動します' : 'Real runtime — kind上でサンプルを起動します'}</strong>
          <p>{IS_DEMO ? 'ブラウザ内だけの模擬動作です。LLMはモックで費用はかかりません。入力・操作は送信されず、再読み込みでリセットされます。' : system?.runtime_mode === 'mock' ? 'UI・API・状態遷移の開発用です。模擬起動ではプレビューURLを発行しません。' : google ? '信頼済みの固定サンプルを登録ユーザーと共有できます。' : 'localhost専用・信頼済みテンプレート限定。外部公開や任意コードの実行には対応していません。'}</p>
        </div>
        <span className="mode-tag">{IS_DEMO ? 'DEMO' : system?.runtime_mode ?? (error ? 'OFFLINE' : 'CONNECTING')}</span>
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
                  <span className="app-row-copy"><strong>{sandbox.name}</strong><span>{sandbox.owner_email === session.email ? '自分のアプリ' : '共有されたアプリ'}<span className="row-divider">·</span>{formatDate(sandbox.updated_at)}</span></span>
                  <span className={`status-dot ${sandbox.status}`} title={statusLabel(sandbox, system?.runtime_mode)} aria-label={statusLabel(sandbox, system?.runtime_mode)} />
                </button>
              </li>)}</ul>}
        </aside>

        <article className="detail-panel" aria-label="アプリの詳細" data-testid="sandbox-detail">
          {!selected ? <div className="welcome-state"><div className="welcome-art" aria-hidden="true"><span /><span /><span /></div><p className="eyebrow">A SMALL START. A WORKING IDEA.</p><h2>ここから、ひとつ動かす。</h2><p>左のアプリを選ぶか、サンプルを登録してください。<br />実際の状態を確認しながら、何度でも試せます。</p><div className="lifecycle-guide"><span>登録</span><i>→</i><span>起動</span><i>→</i><span>確認</span><i>→</i><span>停止</span></div></div>
            : <>
              <div className="detail-heading"><div className="detail-title"><span className="app-avatar large" aria-hidden="true">{selected.name.slice(0, 1).toUpperCase()}</span><div><p className="eyebrow">{selected.template_id === 'management-dashboard' ? '経営管理' : 'HELLO WEB'}</p><h2>{selected.name}</h2></div></div><span className={`status-badge ${selected.status}`} data-testid="sandbox-status"><span />{statusLabel(selected, system?.runtime_mode)}</span></div>
              {!owned && <p className="inline-notice">{selected.owner_email} から共有されたアプリです。閲覧のみ利用できます。</p>}
              <div className="detail-actions">
                <button className="button primary" onClick={() => { void act(selected, 'start'); }} disabled={busy || !owned || deleted || !['stopped', 'failed'].includes(selected.status)}><span aria-hidden="true">▷</span> 起動</button>
                <button className="button secondary" onClick={() => { void act(selected, 'stop'); }} disabled={busy || !owned || deleted || !['starting', 'running', 'failed'].includes(selected.status)}><span aria-hidden="true">□</span> 停止</button>
                <button className="button danger-quiet" onClick={() => setDeleteTarget(selected)} disabled={busy || !owned || deleted}>削除</button>
                {owned && !deleted && <button className="button secondary" onClick={() => setShareTarget(selected)} disabled={busy}>共有設定</button>}
                {busy && <span className="action-progress" role="status"><span className="spinner" />送信中…</span>}
              </div>
              {notice && <p className="inline-notice">{notice}</p>}
              {selected.error && <div className="runtime-error" role="alert"><strong>{selected.error.code}</strong><p>{selected.error.message}</p><p>停止・削除で実行リソースを片づけるか、起動を再試行できます。</p></div>}
              {DemoBuilder && !deleted ? <Suspense fallback={<p role="status">画面を準備中…</p>}><DemoBuilder key={selected.id} sandbox={selected} /></Suspense> : <>
              <section className="preview-card" aria-label="プレビュー"><div><span className="section-kicker">PREVIEW</span><h3>{IS_DEMO ? selected.status === 'running' ? 'サンプル画面の見本を開けます' : '起動操作を試してみましょう' : href || protectedPreview ? 'アプリの準備ができました' : selected.status === 'deleted' ? 'アプリを削除しました' : system?.runtime_mode === 'mock' ? '模擬実行モード' : selected.status === 'starting' ? '起動を確認しています' : '起動すると、ここから開けます'}</h3>
                <p>{IS_DEMO ? '実アプリは起動しません。起動後は、固定サンプルの静的な画面見本を開けます。' : protectedPreview ? 'サンプルをこの画面で開きます。' : href ? '観測済みのサンプルアプリを別タブで開きます。' : system?.runtime_mode === 'mock' ? 'このモードでは実アプリもプレビューURLも作成しません。' : selected.status === 'starting' ? 'Podの準備とHTTP応答をworkerが確認しています。' : '実行リソースの準備が完了するとURLが表示されます。'}</p></div>
                {protectedPreview ? <button className="button primary" onClick={() => setPreviewTarget(selected.id)}>アプリを開く</button> : href ? <a className="button primary" href={href} target="_blank" rel="noopener noreferrer">アプリを開く <span aria-hidden="true">↗</span></a> : IS_DEMO && selected.status === 'running' ? <a className="button primary" href={`${import.meta.env.BASE_URL}demo-preview.html`} target="_blank" rel="noopener noreferrer">サンプル画面を見る <span aria-hidden="true">↗</span></a> : <span className="preview-placeholder" aria-hidden="true">↗</span>}
              </section>
              </>}
              <dl className="metadata-grid"><div className="full-metadata"><dt>所有者</dt><dd>{selected.owner_email}</dd></div><div><dt>希望する状態</dt><dd>{selected.desired_state}</dd></div><div><dt>自動停止予定</dt><dd data-testid="expires-at">{formatDate(selected.expires_at)}</dd></div><div><dt>テンプレート</dt><dd>{selected.template_id}</dd></div><div><dt>最終更新</dt><dd>{formatDate(selected.updated_at)}</dd></div><div><dt>Generation</dt><dd>{selected.generation}</dd></div><div><dt>登録日時</dt><dd>{formatDate(selected.created_at)}</dd></div><div className="full-metadata"><dt>アプリID</dt><dd className="mono">{selected.id}</dd></div></dl>
              {operation && <section className="operation-card" aria-label="最新の操作" data-testid="operation-status"><div><span className="section-kicker">LATEST OPERATION</span><h3>{actionLabels[operation.action]} · {operationLabels[operation.status]}</h3></div><p>試行 {operation.attempt_count} 回 / 更新 {formatDate(operation.updated_at)}</p>{operation.error && <p role="alert">{operation.error.code}: {operation.error.message}</p>}</section>}
              <p className="detail-footnote">停止は管理レコードを残し、実行を止めます。削除は対象アプリの実行リソースを除去します。</p>
            </>}
        </article>
      </section>
      <footer className="footer"><span>ProtoHub v0<span className="row-divider">·</span>{IS_DEMO ? '操作デモ' : google ? 'Google ログイン' : 'Local development'}</span><span>{IS_DEMO ? 'API・LLM通信なし / 再読み込みでリセット' : google ? '登録ユーザー / 信頼済みサンプル専用' : '信頼済みサンプル専用 / 本番認証・悪性コード隔離は未対応'}</span></footer>
    </main>
    {shareTarget && (DemoShareEditor && liveShareTarget
      ? <Modal title="アプリの共有" onClose={closeShares} wide><Suspense fallback={<p role="status">共有設定を準備中…</p>}><DemoShareEditor key={shareTarget.id} sandbox={liveShareTarget} onSaved={() => setNotice('共有設定を保存しました（デモ）。共有先の画面も確認できます。')} /></Suspense></Modal>
      : <ShareEditor sandbox={shareTarget} signal={lifetime.current.signal} onClose={closeShares} onSaved={() => { setShareTarget(null); setNotice('共有設定を保存しました。'); }} />)}
    {protectedPreview && selected && previewTarget === selected.id && <Modal title={selected.name} onClose={closePreview} wide>
      <GooglePreview key={protectedPreview} url={protectedPreview} token={session.token} title={selected.name} />
    </Modal>}
    {showAiStudio && AiStudio && <Modal title="Geminiでアプリを作成" onClose={closeAiStudio} wide><Suspense fallback={<p role="status">作成画面を読み込み中…</p>}><AiStudio onClose={closeAiStudio} /></Suspense></Modal>}
    {showAiCreate && DemoCreation && <Modal title="AIでアプリを作成" onClose={closeAiCreate}><Suspense fallback={<p role="status">テンプレートを準備中…</p>}><DemoCreation busy={busy} onCreate={(name, template, ttl, instruction, plan) => { void create(name, template, ttl, instruction, plan); }} /></Suspense>{actionError && <p role="alert" className="form-error">{actionError.message}</p>}</Modal>}
    {showCreate && <Modal title="サンプルアプリを登録" onClose={closeCreate}><Registration templates={templates} busy={busy} onCreate={(name, template, ttl) => { void create(name, template, ttl); }} />{actionError && <p role="alert" className="form-error">{actionError.message}</p>}</Modal>}
    {deleteTarget && <Modal title="アプリを削除" onClose={closeDelete}><p className="delete-copy"><strong>「{deleteTarget.name}」</strong>を削除しますか？</p><p className="muted">このアプリの実行リソースを除去します。他のアプリには影響しません。管理上の削除記録は保持します。</p><div className="modal-actions"><button className="button secondary" onClick={closeDelete} disabled={busy}>キャンセル</button><button className="button danger" onClick={() => { void act(deleteTarget, 'delete'); }} disabled={busy}>{busy ? '削除要求を送信中…' : '削除する'}</button></div>{actionError && <p role="alert" className="form-error">{actionError.message}</p>}</Modal>}
  </div>;
}
