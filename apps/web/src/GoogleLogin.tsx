import { useEffect, useRef, useState } from 'react';

type CodeOptions = {
  client_id: string; scope: string; ux_mode: 'popup'; include_granted_scopes: false;
  select_account: true; callback: (result: { code?: string; error?: string }) => void;
  error_callback: (result: { type?: string }) => void;
};
type OAuth = { initCodeClient: (options: CodeOptions) => { requestCode: () => void } };
declare global {
  interface Window { google?: { accounts?: { oauth2?: OAuth } } }
}

const sdkUrl = 'https://accounts.google.com/gsi/client';
let sdkLoad: Promise<OAuth> | undefined;

function loadSDK(): Promise<OAuth> {
  const loaded = window.google?.accounts?.oauth2;
  if (loaded) return Promise.resolve(loaded);
  if (sdkLoad) return sdkLoad;
  sdkLoad = new Promise<OAuth>((resolve, reject) => {
    const script = document.createElement('script');
    const fail = () => {
      window.clearTimeout(timer);
      script.remove();
      sdkLoad = undefined;
      reject(new Error('Google のログイン画面を読み込めませんでした。通信を確認して再試行してください。'));
    };
    const timer = window.setTimeout(fail, 15000);
    script.async = true;
    script.referrerPolicy = 'strict-origin-when-cross-origin';
    script.src = sdkUrl;
    script.onerror = fail;
    script.onload = () => {
      window.clearTimeout(timer);
      const sdk = window.google?.accounts?.oauth2;
      if (sdk) resolve(sdk);
      else fail();
    };
    document.head.appendChild(script);
  });
  return sdkLoad;
}

export default function GoogleLogin({ clientId, busy, onCode }: {
  clientId: string; busy: boolean; onCode: (code: string) => void;
}) {
  const client = useRef<ReturnType<OAuth['initCodeClient']> | null>(null);
  const submit = useRef(onCode);
  useEffect(() => { submit.current = onCode; }, [onCode]);
  const [state, setState] = useState<'loading' | 'ready' | 'failed' | 'popup'>('loading');
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    void loadSDK().then(sdk => {
      if (!active) return;
      client.current = sdk.initCodeClient({
        client_id: clientId, scope: 'openid email', ux_mode: 'popup',
        include_granted_scopes: false, select_account: true,
        callback: result => {
          if (!active) return;
          setState('ready');
          if (result.error || !result.code) setError('Google ログインが許可されませんでした。');
          else { setError(''); submit.current(result.code); }
        },
        error_callback: result => {
          if (!active) return;
          setState('ready');
          setError(result.type === 'popup_closed' ? 'ログイン画面を閉じました。'
            : 'ログイン画面を開けませんでした。ポップアップを許可して再試行してください。');
        },
      });
      setState('ready');
    }).catch(() => {
      if (active) { setState('failed'); setError('Google のログイン画面を読み込めませんでした。通信を確認してください。'); }
    });
    return () => { active = false; client.current = null; };
  }, [clientId, attempt]);

  function start() {
    setError('');
    if (state === 'failed') { setState('loading'); setAttempt(n => n + 1); return; }
    if (!client.current || state !== 'ready') return;
    setState('popup');
    try { client.current.requestCode(); }
    catch { setState('ready'); setError('Google のログイン画面を開けませんでした。再試行してください。'); }
  }
  return <>
    <p className="muted">登録済みの Google アカウントでログインしてください。</p>
    <button className="button primary full-width" onClick={start} disabled={busy || state === 'loading' || state === 'popup'}>
      {state === 'failed' ? '読み込みを再試行' : busy || state === 'popup' ? 'ログイン中…' : 'Google でログイン'}
    </button>
    {error && <p className="form-error" role="alert">{error}</p>}
  </>;
}
