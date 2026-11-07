import { useEffect, useRef, useState } from 'react';
import type { Sandbox } from './api';
import { loadDraft, previewLink, reviseDraft, saveDraft, undoDraft } from './demo-builder';
import DemoPreview from './DemoPreview';
import AppBriefSummary from './AppBriefSummary';

export default function DemoBuilder({ sandbox }: { sandbox: Sandbox }) {
  const [draft, setDraft] = useState(() => loadDraft(sandbox.id, sandbox.template_id));
  const [instruction, setInstruction] = useState('');
  const [pending, setPending] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const chat = useRef<HTMLDivElement>(null);
  useEffect(() => () => { if (timer.current !== null) clearTimeout(timer.current); }, []);
  useEffect(() => {
    if (chat.current) chat.current.scrollTop = chat.current.scrollHeight;
  }, [draft.messages, pending]);
  const submit = (text: string) => {
    const value = text.trim();
    if (!value || value.length > 500 || timer.current !== null) return;
    setInstruction(value);
    setPending(true);
    timer.current = setTimeout(() => {
      const next = reviseDraft(draft, value);
      saveDraft(sandbox.id, next);
      setDraft(next);
      setInstruction('');
      setPending(false);
      timer.current = null;
    }, 650);
  };
  const undo = () => {
    const next = undoDraft(draft);
    saveDraft(sandbox.id, next);
    setDraft(next);
  };
  const suggestions = sandbox.template_id === 'management-dashboard'
    ? ['利益推移グラフを追加', '部門別の表を追加', '青い配色に変更']
    : ['タイトルを「チームポータル」に変更', '説明を「アイデアをチームで試す場所」に変更', '青い配色に変更'];
  return <section className="demo-builder" aria-label="AIでアプリを編集">
    <div className="studio-heading"><div><h3>AIに指示して、画面を育てる</h3><p>モックAI · 対応する指示をもとに、画面見本を変更します。</p></div><span className="mode-tag">MOCK AI</span></div>
    {draft.plan && <details className="brief-original"><summary>作成時の目的と確認内容</summary><AppBriefSummary plan={draft.plan} />
      <p className="field-hint">追加の指示で変更した画面とは区別して、作成時の内容を残しています。</p></details>}
    <div className="demo-chat" ref={chat} role="log" aria-label="AIとの会話" aria-live="polite" aria-relevant="additions text">
      {draft.messages.map((message,index) => <div key={index} className={`chat-message ${message.role}`}>
        <strong>{message.role === 'user' ? 'あなた' : 'モックAI'}</strong><p>{message.text}</p></div>)}
      {pending && <p className="chat-pending" role="status">画面の変更を準備中…</p>}
    </div>
    <form className="demo-prompt" onSubmit={event => { event.preventDefault(); submit(instruction); }}>
      <label htmlFor="ai-instruction">追加の指示・修正したいこと</label>
      <textarea id="ai-instruction" name="instruction" rows={2} autoComplete="off" maxLength={500}
        placeholder="例: 利益推移グラフを追加して、配色を青に変更…" value={instruction} onChange={event => setInstruction(event.target.value)} disabled={pending} />
      <div className="prompt-actions"><small>LLM通信なし・費用なし。最大500文字。</small><button className="button primary" disabled={pending || !instruction.trim()}>{pending ? '変更中…' : '指示を反映'}</button></div>
    </form>
    <div className="prompt-suggestions" aria-label="試せる指示">{suggestions.map(text =>
      <button className="suggestion-button" key={text} disabled={pending} onClick={() => submit(text)}>{text}</button>)}</div>
    <div className="studio-preview-heading"><h3>プレビュー <span>v{draft.version}</span></h3>
      <div className="studio-preview-actions"><button className="text-button" onClick={undo} disabled={pending || !draft.history.length}>ひとつ戻す</button>
        {sandbox.status === 'running' && <a className="button secondary" href={previewLink(draft.config)} target="_blank" rel="noopener noreferrer">サンプル画面を見る <span aria-hidden="true">↗</span></a>}</div></div>
    <DemoPreview config={draft.config} />
    <p className="field-hint">固定の画面見本です。実アプリの起動・コード生成・データ接続は行いません。変更と会話は再読み込みでリセットされます。別タブは開いた時点の画面見本です。</p>
  </section>;
}
