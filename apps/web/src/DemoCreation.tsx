import { useEffect, useRef, useState } from 'react';
import type { TemplateId } from './api';
import { defaultConfig } from './demo-builder';
import { buildPreviewPlan, validateBrief } from './app-brief';
import type { AppBrief, BriefErrors, PreviewPlan } from './app-brief';
import AppBriefSummary from './AppBriefSummary';
import './demo-studio.css';
import './app-brief.css';

const steps = ['目的と利用者', '画面の内容', '作成内容の確認'];

export default function DemoCreation({ busy, onCreate }: {
  busy: boolean; onCreate: (name: string, template: TemplateId, ttl: number, instruction: string, plan: PreviewPlan) => void;
}) {
  const [config, setConfig] = useState(() => ({ ...defaultConfig('management-dashboard'), trend: true }));
  const [brief, setBrief] = useState<AppBrief>({ purpose: '', audience: '', success: '' });
  const [step, setStep] = useState(0);
  const [errors, setErrors] = useState<BriefErrors>({});
  const form = useRef<HTMLFormElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, [step]);
  useEffect(() => { form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(); }, [errors]);

  const fieldError = (key: keyof BriefErrors) => errors[key]
    ? <p className="brief-error" id={`brief-${key}-error`}>{errors[key]}</p> : null;
  const briefField = (key: keyof AppBrief, label: string, placeholder: string) => <div className="brief-field">
    <label htmlFor={`brief-${key}`}>{label}</label>
    <textarea id={`brief-${key}`} name={key} rows={2} autoComplete="off" maxLength={300}
      value={brief[key]} onChange={event => setBrief(previous => ({ ...previous, [key]: event.target.value }))}
      aria-invalid={Boolean(errors[key])} aria-describedby={errors[key] ? `brief-${key}-error` : undefined}
      disabled={busy} placeholder={placeholder} />
    {fieldError(key)}
  </div>;
  const next = () => {
    const all = validateBrief(brief, config);
    const relevant = step === 0 ? Object.fromEntries(Object.entries(all).filter(([key]) => ['title', 'purpose', 'audience'].includes(key))) : all;
    setErrors(relevant);
    if (Object.keys(relevant).length) return;
    if (step < 2) setStep(step + 1);
    else {
      const plan = buildPreviewPlan(brief, config);
      onCreate(plan.config.title, plan.config.template, 900, '', plan);
    }
  };

  return <form className="registration-form app-brief-form" ref={form} noValidate onSubmit={event => {
    event.preventDefault();
    if (!busy) next();
  }}>
    <ol className="brief-steps" aria-label="作成の手順">{steps.map((label, index) =>
      <li key={label} aria-current={step === index ? 'step' : undefined}><span aria-hidden="true">{index + 1}</span>{label}</li>)}</ol>
    <h3 ref={heading} tabIndex={-1} className="brief-step-heading">{steps[step]}</h3>
    <p className="field-hint">画面見本を作る操作デモです。コード生成・実データ接続・実アプリの起動は行いません。入力内容は再読み込みでリセットされます。</p>
    {step === 0 && <>
      <p className="muted">標準の構成を使います。まず、目的と使う人を教えてください。</p>
      <label htmlFor="ai-app-name">アプリ名</label>
      <input id="ai-app-name" name="name" autoComplete="off" maxLength={64} value={config.title}
        onChange={event => setConfig(previous => ({ ...previous, title: event.target.value }))}
        disabled={busy} aria-invalid={Boolean(errors.title)} aria-describedby={errors.title ? 'brief-title-error' : undefined} />
      {fieldError('title')}
      {briefField('purpose', '何をできるようにしたいですか？', '例: 毎月の予実を確認して、対応が必要な部門を見つけたい…')}
      {briefField('audience', '誰が使いますか？', '例: 月次会議に参加する担当者…')}
      <fieldset className="template-picker"><legend>最初に試す画面</legend>
        {([
          ['hello-web', '案内用のWebページ', 'タイトルと説明文を使ったシンプルなページ。'],
          ['management-dashboard', '経営管理ダッシュボード', '売上・費用・利益と予実を確認する画面。'],
        ] as const).map(([id, label, description]) => <label key={id} className={`template-choice ${config.template === id ? "chosen" : ""}`}>
          <input type="radio" name="ai-template" value={id} checked={config.template === id} onChange={() => setConfig(previous => ({
            ...defaultConfig(id), trend: id === 'management-dashboard',
            title: previous.title === defaultConfig(previous.template).title ? defaultConfig(id).title : previous.title,
          }))} disabled={busy} /><span><strong>{label}</strong><small>{description}</small></span>
        </label>)}
      </fieldset>
    </>}
    {step === 1 && <>
      <label htmlFor="brief-subtitle">画面に表示する説明文</label>
      <textarea id="brief-subtitle" name="subtitle" autoComplete="off" maxLength={160} rows={2} value={config.subtitle}
        onChange={event => setConfig(previous => ({ ...previous, subtitle: event.target.value }))}
        disabled={busy} aria-invalid={Boolean(errors.subtitle)} aria-describedby={errors.subtitle ? 'brief-subtitle-error' : undefined} />
      {fieldError('subtitle')}
      {config.template === 'management-dashboard' && <fieldset className="brief-options"><legend>追加して確認したい内容</legend>
        {([['trend', '売上・利益の推移グラフ'], ['departments', '部門別の表'], ['cashFlow', 'キャッシュフローカード']] as const).map(([key, label]) =>
          <label key={key}><input type="checkbox" name={key} checked={config[key]} onChange={event =>
            setConfig(previous => ({ ...previous, [key]: event.target.checked }))} disabled={busy} />{label}</label>)}
      </fieldset>}
      <fieldset className="brief-options brief-colors"><legend>配色</legend>
        {([['purple', '紫'], ['blue', '青'], ['green', '緑']] as const).map(([value, label]) =>
          <label key={value}><input type="radio" name="color" checked={config.color === value} onChange={() =>
            setConfig(previous => ({ ...previous, color: value }))} disabled={busy} />{label}</label>)}
      </fieldset>
      {briefField('success', '画面見本で、どんなことを確かめたいですか？', '例: 会議で部門ごとの差を見つけやすいか確かめたい…')}
      <p className="field-hint">目的や確認したいことは要件として残します。画面への反映は、上で選んだ表示内容と配色が対象です。サンプルデータの保存や外部接続の質問はありません。</p>
    </>}
    {step === 2 && <AppBriefSummary plan={buildPreviewPlan(brief, config)} />}
    <div className="brief-actions">
      {step > 0 && <button type="button" className="button secondary" disabled={busy} onClick={() => { setErrors({}); setStep(step - 1); }}>前の内容を修正</button>}
      <button type="submit" className="button primary" disabled={busy}>{busy ? '作成中…' : step === 2 ? 'この内容で画面見本を作成' : step === 0 ? '画面の内容を決める' : '作成内容を確認'}</button>
    </div>
  </form>;
}
