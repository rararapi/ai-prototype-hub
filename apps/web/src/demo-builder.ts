import type { TemplateId } from './api';
import type { PreviewPlan } from './app-brief';

export type DemoConfig = {
  template: TemplateId; title: string; subtitle: string;
  color: 'purple' | 'blue' | 'green'; trend: boolean; departments: boolean; cashFlow: boolean;
};
export type DemoMessage = { role: 'user' | 'assistant'; text: string };
export type DemoDraft = { config: DemoConfig; history: DemoConfig[]; messages: DemoMessage[]; version: number; plan?: PreviewPlan };
const drafts = new Map<string, DemoDraft>();

export function defaultConfig(template: TemplateId): DemoConfig {
  return {
    template, title: template === 'management-dashboard' ? '経営管理ダッシュボード' : 'Hello Web',
    subtitle: template === 'management-dashboard' ? '売上・費用・利益と予実を、ひと目で。' : '小さく作って、試して、育てよう。',
    color: 'purple', trend: false, departments: false, cashFlow: false,
  };
}

export function interpretInstruction(config: DemoConfig, instruction: string) {
  const next = { ...config };
  const changes: string[] = [];
  const update = <K extends keyof DemoConfig>(key: K, value: DemoConfig[K], label: string) => {
    if (next[key] !== value) { next[key] = value; changes.push(label); }
  };
  const title = /(?<!サブ)タイトル(?:を|は|[:：])?\s*[「『"]([^」』"]{1,64})[」』"]/.exec(instruction);
  const subtitle = /(?:説明|サブタイトル)(?:を|は|[:：])?\s*[「『"]([^」』"]{1,160})[」』"]/.exec(instruction);
  if (title) update('title', title[1], 'タイトルを変更');
  if (subtitle) update('subtitle', subtitle[1], '説明文を変更');
  // Quoted copy is content, not a command to change colors or widgets.
  const commands = instruction.replace(/[「『"][^」』"]*[」』"]/g, '');
  if (/青|ブルー/.test(commands)) update('color', 'blue', '青い配色に変更');
  else if (/緑|グリーン/.test(commands)) update('color', 'green', '緑の配色に変更');
  else if (/紫|パープル/.test(commands)) update('color', 'purple', '紫の配色に変更');
  if (config.template === 'management-dashboard') {
    const remove = '(?:削除|非表示|消して|外して|なし|不要|除いて|なくして)';
    const features = [
      { key: 'trend', pattern: '(?:利益推移グラフ|売上推移グラフ|推移グラフ|グラフ|チャート)', label: '売上・利益推移グラフ' },
      { key: 'departments', pattern: '(?:部門(?:別)?(?:の)?(?:表)?|部門一覧)', label: '部門別の表' },
      { key: 'cashFlow', pattern: '(?:キャッシュフロー|キャッシュフローカード)', label: 'キャッシュフローカード' },
    ] as const;
    for (const feature of features) {
      if (!new RegExp(feature.pattern).test(commands)) continue;
      const disabled = new RegExp(feature.pattern + '\\s*(?:を|は|も|の表示を|表示を)?\\s*' + remove).test(commands);
      update(feature.key, !disabled, feature.label + (disabled ? 'を削除' : 'を追加'));
    }
  }
  return {
    config: next, changed: changes.length > 0,
    reply: changes.length ? changes.join('、') + 'しました。下の画面見本で確認できます。'
      : 'この指示では画面を変更していません。モックで対応するのは、配色・引用符付きタイトル/説明文'
        + (config.template === 'management-dashboard' ? '・推移グラフ・部門別の表・キャッシュフローカード' : '') + 'です。下の指示例も試せます。',
  };
}

export function seedDraft(id: string, template: TemplateId, instruction = '', plan?: PreviewPlan) {
  if (plan && plan.config.template !== template) throw new Error('Template does not match the preview plan');
  const initial = defaultConfig(template);
  const result = interpretInstruction(initial, instruction);
  const draft: DemoDraft = {
    config: plan ? { ...plan.config } : result.config, history: [], version: 1,
    ...(plan ? { plan: { ...plan, brief: { ...plan.brief }, config: { ...plan.config } } } : {}),
    messages: [
      ...(instruction ? [{ role: 'user' as const, text: instruction.slice(0, 500) }] : []),
      { role: 'assistant', text: '固定テンプレートから画面見本を用意しました。'
        + (result.changed ? result.reply : '追加の指示で配色や表示内容を変えてみましょう。')
        + ' モックのため、コード生成やLLM通信は行いません。' },
    ],
  };
  drafts.set(id, draft);
  return draft;
}
export function loadDraft(id: string, template: TemplateId) {
  return drafts.get(id) ?? seedDraft(id, template);
}
export function reviseDraft(draft: DemoDraft, instruction: string): DemoDraft {
  const result = interpretInstruction(draft.config, instruction);
  return {
    ...draft,
    config: result.config,
    history: result.changed ? [...draft.history, draft.config].slice(-10) : draft.history,
    version: draft.version + (result.changed ? 1 : 0),
    messages: [...draft.messages, { role: 'user' as const, text: instruction.slice(0, 500) },
      { role: 'assistant' as const, text: result.reply }].slice(-30),
  };
}
export function undoDraft(draft: DemoDraft): DemoDraft {
  if (!draft.history.length) return draft;
  return { ...draft, config: draft.history.at(-1)!, history: draft.history.slice(0, -1),
    version: draft.version + 1, messages: [...draft.messages,
      { role: 'assistant' as const, text: 'ひとつ前の画面に戻しました。' }].slice(-30) };
}
export function saveDraft(id: string, draft: DemoDraft) { drafts.set(id, draft); }

export function previewLink(config: DemoConfig) {
  return import.meta.env.BASE_URL + 'demo-preview.html#' + encodeURIComponent(JSON.stringify(config));
}

export function parsePreviewConfig(hash: string): DemoConfig {
  const fallback = defaultConfig('hello-web');
  try {
    if (hash.length > 4000) return fallback;
    const value: unknown = JSON.parse(decodeURIComponent(hash.replace(/^#/, '')));
    if (!value || typeof value !== 'object') return fallback;
    const config = value as Partial<DemoConfig>;
    if (!['hello-web', 'management-dashboard'].includes(config.template ?? '')
      || typeof config.title !== 'string' || !config.title.trim() || config.title.length > 64
      || typeof config.subtitle !== 'string' || config.subtitle.length > 160
      || !['purple', 'blue', 'green'].includes(config.color ?? '')
      || !['trend', 'departments', 'cashFlow'].every(key => typeof config[key as keyof DemoConfig] === 'boolean')) return fallback;
    // Keep only known display fields; no HTML, URL, style or executable code is accepted.
    return { template: config.template!, title: config.title, subtitle: config.subtitle,
      color: config.color!, trend: config.trend!, departments: config.departments!, cashFlow: config.cashFlow! };
  } catch { return fallback; }
}
