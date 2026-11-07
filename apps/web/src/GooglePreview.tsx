import { useEffect, useState } from 'react';
import { SESSION_EXPIRED_EVENT, sessionStore } from './api';

const uuid = /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i;

export function registeredPreviewURL(origin: string | null | undefined, id: string) {
  if (!origin || !uuid.test(id)) return null;
  try {
    const base = new URL(origin);
    const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(base.hostname);
    if (base.origin !== origin || base.origin === window.location.origin ||
        (base.protocol !== 'https:' && !(loopback && base.protocol === 'http:'))) return null;
    return new URL('/apps/' + id + '/', base).href;
  } catch { return null; }
}

export default function GooglePreview({ url, token, title }: {
  url: string; token: string; title: string;
}) {
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      const response = await fetch(url, {
        method: 'GET', signal: controller.signal, credentials: 'omit', redirect: 'error',
        cache: 'no-store', referrerPolicy: 'no-referrer',
        headers: { Accept: 'text/html', Authorization: 'Bearer ' + token },
      });
      if (response.status === 401 && sessionStore.get()?.token === token) {
        window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT, { detail: token }));
      }
      if (!response.ok || response.headers.get('content-type')?.split(';')[0].trim() !== 'text/html') {
        throw new Error('preview unavailable');
      }
      const content = await response.text();
      if (!controller.signal.aborted) setHtml(content);
    }
    void load().catch(() => {
      if (!controller.signal.aborted) setError('このアプリのプレビューを開けません。アクセス権と起動状態を確認してください。');
    });
    return () => controller.abort();
  }, [url, token]);
  if (error) return <p role="alert" className="form-error">{error}</p>;
  if (html === null) return <p role="status">プレビューを読み込み中…</p>;
  // The fixed template needs inline script/style for its counter, and no network resources.
  const policy = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'";
  const document = '<!doctype html><meta http-equiv="Content-Security-Policy" content="' + policy +
    '"><meta charset="utf-8">' + html.replace(/^\s*<!doctype html>/i, '');
  return <iframe title={title} sandbox="allow-scripts" referrerPolicy="no-referrer"
    style={{ width: '100%', height: 'min(60vh, 32rem)', border: 0 }} srcDoc={document} />;
}
