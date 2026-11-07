import type { DemoConfig } from './demo-builder';

// A display-only profile, independent of Sandbox/Operation runtime state.
export const PREVIEW_PROFILE = {
  id: 'trusted-preview-v1',
  fixed: ['固定テンプレートから画面見本を作成', '架空のサンプルデータを使用', '入力内容は外部へ送信せず、この画面を開いている間だけ保持'],
  excluded: ['実データの保存・外部サービスとの接続', 'ログイン・権限の実装', 'コード生成・実アプリの起動・公開'],
} as const;

export type AppBrief = { purpose: string; audience: string; success: string };
export type PreviewPlan = { profile: typeof PREVIEW_PROFILE.id; brief: AppBrief; config: DemoConfig };
export type BriefErrors = Partial<Record<keyof AppBrief | 'title' | 'subtitle', string>>;

export function validateBrief(brief: AppBrief, config: DemoConfig): BriefErrors {
  const errors: BriefErrors = {};
  for (const key of ['purpose', 'audience', 'success'] as const) {
    if (!brief[key].trim()) errors[key] = '内容を入力してください。';
    else if (brief[key].trim().length > 300) errors[key] = '300文字以内で入力してください。';
  }
  if (!config.title.trim() || config.title.trim().length > 64) errors.title = 'アプリ名を1〜64文字で入力してください。';
  if (config.subtitle.trim().length > 160) errors.subtitle = '説明文を160文字以内で入力してください。';
  return errors;
}

export function buildPreviewPlan(brief: AppBrief, config: DemoConfig): PreviewPlan {
  if (Object.keys(validateBrief(brief, config)).length) throw new Error('作成内容を確認してください。');
  return {
    profile: PREVIEW_PROFILE.id,
    brief: { purpose: brief.purpose.trim(), audience: brief.audience.trim(), success: brief.success.trim() },
    config: { ...config, title: config.title.trim(), subtitle: config.subtitle.trim(),
      trend: config.template === 'management-dashboard' && config.trend,
      departments: config.template === 'management-dashboard' && config.departments,
      cashFlow: config.template === 'management-dashboard' && config.cashFlow },
  };
}

export function previewChecks(config: DemoConfig): string[] {
  return [
    `画面に「${config.title}」を表示する`,
    ...(config.subtitle ? ['説明文を表示する'] : []),
    config.template === 'management-dashboard' ? '売上・費用・営業利益・予実のサンプルを表示する' : '案内用のWebページを表示する',
    ...(config.trend ? ['売上・利益の推移グラフを表示する'] : []),
    ...(config.departments ? ['部門別の表を表示する'] : []),
    ...(config.cashFlow ? ['キャッシュフローカードを表示する'] : []),
    `${{ purple: "紫", blue: "青", green: "緑" }[config.color]}の配色を使う`,
  ];
}
