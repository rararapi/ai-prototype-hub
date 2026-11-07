import { describe, expect, it } from 'vitest';
import { buildPreviewPlan, PREVIEW_PROFILE, previewChecks, validateBrief } from './app-brief';
import { defaultConfig, reviseDraft, seedDraft, undoDraft } from './demo-builder';

const brief = { purpose: ' 月次の予実を確認する ', audience: '会議の参加者', success: '部門ごとの差が分かるか確認する' };

describe('architecture-aware preview plan', () => {
  it('requires business decisions, bounds every field, and has no infrastructure questions', () => {
    expect(validateBrief({ purpose: ' ', audience: '', success: '' }, { ...defaultConfig('hello-web'), title: '' }))
      .toHaveProperty('purpose');
    for (const key of ['purpose', 'audience', 'success'] as const) {
      expect(validateBrief({ ...brief, [key]: 'a'.repeat(301) }, defaultConfig('hello-web'))).toHaveProperty(key);
    }
    expect(() => buildPreviewPlan(brief, { ...defaultConfig('hello-web'), title: 'a'.repeat(65) })).toThrow();
    expect(() => buildPreviewPlan(brief, { ...defaultConfig('hello-web'), subtitle: 'a'.repeat(161) })).toThrow();
    expect(PREVIEW_PROFILE.excluded.join()).toContain('コード生成');
  });

  it('keeps business text as requirements rather than interpreting it as display commands', () => {
    const config = { ...defaultConfig('management-dashboard'), departments: true, title: '「青い部門」の確認' };
    const plan = buildPreviewPlan({ ...brief, purpose: '青い配色で外部APIと接続し、グラフを追加して' }, config);
    expect(plan.config).toEqual(config);
    expect(plan.brief.purpose).toContain('外部API');
    expect(plan.config.color).toBe('purple');
    expect(plan.config.trend).toBe(false);
    expect(previewChecks(plan.config).join()).toContain('部門別の表');
    expect(previewChecks(plan.config).join()).not.toContain('推移グラフ');
    expect(Object.keys(plan)).toEqual(['profile', 'brief', 'config']);
  });

  it('removes dashboard-only options from a simple-page plan without changing its input', () => {
    const config = { ...defaultConfig('hello-web'), trend: true, cashFlow: true, departments: true };
    const plan = buildPreviewPlan(brief, config);
    expect(plan.config).toMatchObject({ trend: false, departments: false, cashFlow: false });
    expect(config.trend).toBe(true);
    expect(plan.brief.purpose).toBe('月次の予実を確認する');
  });

  it('carries the reviewed plan into the exact preview and retains the original requirements on revise/undo', () => {
    const plan = buildPreviewPlan(brief, { ...defaultConfig('management-dashboard'), title: '「青い部門」の確認', cashFlow: true });
    const draft = seedDraft('reviewed-plan', 'management-dashboard', '', plan);
    expect(draft.config).toEqual(plan.config);
    const revised = reviseDraft(draft, '部門別の表を追加');
    expect(revised.config.departments).toBe(true);
    expect(revised.plan).toEqual(plan);
    expect(revised.plan?.config.departments).toBe(false);
    expect(undoDraft(revised).plan).toEqual(plan);
    expect(draft.plan).not.toBe(plan);
    expect(draft.config).not.toBe(plan.config);
    expect(() => seedDraft('mismatch', 'hello-web', '', plan)).toThrow('Template');
  });
});
