import { createRoot } from 'react-dom/client';
import DemoPreview from './DemoPreview';
import { parsePreviewConfig } from './demo-builder';
import './styles.css';

const config = parsePreviewConfig(window.location.hash);
createRoot(document.getElementById('root')!).render(
  <main className="standalone-preview">
    <div className="standalone-notice"><a href="./">ProtoHub 操作デモへ</a><span>画面見本 · モックAI · 架空データ</span></div>
    <DemoPreview config={config} standalone />
    <p className="field-hint">実アプリやLLMには接続していません。開いた時点の画面見本です。変更を再確認するには、元の画面から開き直してください。</p>
  </main>,
);
