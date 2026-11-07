import { useEffect, useState } from 'react';
import type { Sandbox } from './api';
import { loadDraft } from './demo-builder';
import { DEMO_MEMBERS, demoSharing, recipientState } from './demo-sharing';
import type { DemoMemberId } from './demo-sharing';
import DemoPreview from './DemoPreview';
import './demo-studio.css';

export default function DemoShareEditor({ sandbox, onSaved }: { sandbox: Sandbox; onSaved: () => void }) {
  const [saved, setSaved] = useState(() => demoSharing.get(sandbox.id));
  const [selected, setSelected] = useState<DemoMemberId[]>(saved);
  const [view, setView] = useState<'owner' | 'recipient'>('owner');
  const [viewer, setViewer] = useState<DemoMemberId>('member-a');
  const [notice, setNotice] = useState('');
  const dirty = DEMO_MEMBERS.some(member => saved.includes(member.id) !== selected.includes(member.id));
  const deleted = sandbox.desired_state === 'deleted' || ['deleting', 'deleted'].includes(sandbox.status);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  const memberName = DEMO_MEMBERS.find(member => member.id === viewer)!.name;
  const access = recipientState(sandbox, saved, viewer);
  return <div className="demo-sharing">
    <p className="field-hint share-demo-note">共有体験のモックです。招待メールの送信や本物の認証は行いません。設定は再読み込みでリセットされます。</p>
    <div className="share-view-switch" aria-label="共有デモの表示">
      <button className={view === 'owner' ? 'active' : ''} aria-pressed={view === 'owner'} onClick={() => setView('owner')}>所有者の設定</button>
      <button className={view === 'recipient' ? 'active' : ''} aria-pressed={view === 'recipient'} onClick={() => setView('recipient')}>共有先の画面</button>
    </div>
    {view === 'owner' ? <form onSubmit={event => {
      event.preventDefault();
      if (deleted) return;
      const result = demoSharing.save(sandbox.id, selected);
      setSaved(result);
      setNotice(result.length ? '共有設定を保存しました。共有先の画面を確認できます。' : 'すべての共有を解除しました。');
      onSaved();
    }}>
      <div className="share-app-heading"><h3>{sandbox.name}</h3><span className="share-permission">閲覧のみ</span></div>
      <p className="muted">共有先は画面の閲覧だけができます。AIでの編集・起動・停止・削除・再共有は所有者だけが行います。</p>
      <fieldset className="share-member-picker" disabled={deleted}><legend>共有するメンバー</legend>
        {DEMO_MEMBERS.map(member => <label className="share-member" key={member.id}>
          <input type="checkbox" name="members" value={member.id} checked={selected.includes(member.id)}
            onChange={event => {
              const checked = event.target.checked;
              setNotice('');
              setSelected(current => checked ? [...current, member.id] : current.filter(id => id !== member.id));
            }} />
          <span className="member-avatar" aria-hidden="true">{member.id === 'member-a' ? 'A' : 'B'}</span>
          <span><strong>{member.name}</strong><small>デモ用の共有先</small></span>
          <span className={saved.includes(member.id) ? 'member-granted' : 'member-unshared'}>{saved.includes(member.id) ? '共有中' : '未共有'}</span>
        </label>)}
      </fieldset>
      <p className="field-hint">{saved.length ? `保存済みの共有先: ${saved.map(id => DEMO_MEMBERS.find(member => member.id === id)!.name).join('、')}。` : 'まだ共有先はありません。'} チェックを外して保存すると共有を解除できます。</p>
      {deleted && <p role="alert">削除要求済みのアプリは共有設定を変更できません。</p>}
      <div className="share-save-actions"><button className="button primary" type="submit" disabled={deleted || !dirty}>共有設定を保存</button>
        <button className="button secondary" type="button" onClick={() => setView('recipient')}>共有先の画面を見る</button></div>
    </form> : <div>
      <label className="share-viewer-label" htmlFor="share-viewer">画面を確認するメンバー（デモ）</label>
      <select id="share-viewer" name="viewer" value={viewer} onChange={event => setViewer(event.target.value as DemoMemberId)}>
        {DEMO_MEMBERS.map(member => <option value={member.id} key={member.id}>{member.name}</option>)}
      </select>
      <p className="field-hint">保存済みの設定で、受け取る側の表示を再現します。</p>
      <section className="recipient-frame" data-testid="demo-recipient-view" aria-label="共有先の閲覧画面">
        <div className="recipient-principal"><span className="member-avatar" aria-hidden="true">{viewer === 'member-a' ? 'A' : 'B'}</span><strong>{memberName} の画面</strong><span>共有先</span></div>
        <h3>共有されたアプリ</h3>
        {access === 'denied' ? <div className="recipient-unavailable" role="status"><h4>このメンバーには共有されていません</h4><p>所有者の設定で共有先に追加し、保存すると閲覧できます。</p></div>
          : access === 'deleted' || access === 'deleting' ? <div className="recipient-unavailable" role="status"><h4>{access === 'deleted' ? 'このアプリは削除されました' : 'アプリを削除処理中です'}</h4><p>現在は閲覧できません。</p></div>
            : <><div className="share-app-heading"><h4>{sandbox.name}</h4><span className="share-permission">閲覧のみ</span></div>
              <p className="field-hint">所有者: デモの作成者 · 編集や起動・停止・削除はできません。</p>
              {access === 'ready' ? <DemoPreview config={loadDraft(sandbox.id, sandbox.template_id).config} />
                : <div className="recipient-unavailable" role="status"><h4>{access === 'starting' ? 'アプリを準備中です' : access === 'stopping' ? 'アプリを停止処理中です' : access === 'failed' ? 'アプリの状態を確認してください' : 'アプリは停止中です'}</h4><p>所有者が起動すると、ここで画面を確認できます。</p></div>}
            </>}
      </section>
    </div>}
    {dirty && <p className="share-unsaved" role="status">共有先の変更が未保存です。共有先の画面には、保存済みの設定が使われます。</p>}
    <p className="share-saved-notice" role="status" aria-live="polite">{notice}</p>
  </div>;
}
