import { PREVIEW_PROFILE, previewChecks } from './app-brief';
import type { PreviewPlan } from './app-brief';
import './app-brief.css';

export default function AppBriefSummary({ plan }: { plan: PreviewPlan }) {
  return <div className="app-brief-summary">
    <dl className="brief-facts">
      <div><dt>画面名</dt><dd>{plan.config.title}</dd></div>
      <div><dt>画面の説明文</dt><dd>{plan.config.subtitle || '説明文なし'}</dd></div>
      <div><dt>作る目的</dt><dd>{plan.brief.purpose}</dd></div>
      <div><dt>使う人</dt><dd>{plan.brief.audience}</dd></div>
      <div><dt>利用者が確かめたいこと</dt><dd>{plan.brief.success}</dd></div>
    </dl>
    <h4>今回の画面見本で確認すること</h4>
    <ul>{previewChecks(plan.config).map(check => <li key={check}>{check}</li>)}</ul>
    <p className="field-hint">確認項目は作成時の計画です。テストの合格や、利用目的の実現を示すものではありません。</p>
    <details className="brief-boundaries"><summary>共通の前提と今回の対象外</summary>
      <h4>共通の前提</h4><ul>{PREVIEW_PROFILE.fixed.map(text => <li key={text}>{text}</li>)}</ul>
      <h4>今回の対象外</h4><ul>{PREVIEW_PROFILE.excluded.map(text => <li key={text}>{text}</li>)}</ul>
      <p>対象外の機能が必要な場合は、この画面見本とは別に設計・実装が必要です。</p>
    </details>
  </div>;
}
