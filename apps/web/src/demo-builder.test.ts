import { describe, expect, it } from 'vitest';
import { defaultConfig, interpretInstruction, loadDraft, parsePreviewConfig, previewLink, reviseDraft, saveDraft, seedDraft, undoDraft } from './demo-builder';

describe('deterministic mock AI', () => {
  it('builds the management template from an initial request and refines the visible config', () => {
    const draft = seedDraft('financial', 'management-dashboard', '利益推移グラフを追加して');
    expect(draft.config).toMatchObject({ template: 'management-dashboard', trend: true, departments: false });
    const next = reviseDraft(draft, '部門別の表を追加して、配色を青に変更');
    expect(next.config).toMatchObject({ trend: true, departments: true, color: 'blue' });
    expect(next.messages.at(-1)?.text).toContain('部門別の表を追加');
    expect(next.version).toBe(2);
    expect(undoDraft(next).config).toEqual(draft.config);
    expect(draft.config.departments).toBe(false);
  });

  it('handles removal and cash flow without turning display text into instructions', () => {
    const config = { ...defaultConfig('management-dashboard'), trend: true, departments: true };
    const result = interpretInstruction(config, 'グラフを削除。部門別の表を非表示。キャッシュフローを追加。タイトルを「青い会社」に変更');
    expect(result.config).toMatchObject({ trend: false, departments: false, cashFlow: true, title: '青い会社', color: 'purple' });
    expect(result.reply).toContain('キャッシュフローカードを追加');
  });

  it('changes only the subtitle for a subtitle instruction and scopes removals to each widget', () => {
    const initial = defaultConfig('management-dashboard');
    const copy = interpretInstruction(initial, 'サブタイトルを「月次の予実」に変更');
    expect(copy.config.title).toBe(initial.title);
    expect(copy.config.subtitle).toBe('月次の予実');
    const widgets = interpretInstruction({ ...initial, trend: true }, 'グラフを削除して部門別の表を追加');
    expect(widgets.config).toMatchObject({ trend: false, departments: true });
  });

  it('does not claim unsupported requests changed the screen and bounds undo/chat memory', () => {
    let draft = seedDraft('bounded', 'hello-web');
    const unchanged = reviseDraft(draft, '任意のソースコードを実行して');
    expect(unchanged.config).toEqual(draft.config);
    expect(unchanged.version).toBe(1);
    expect(unchanged.history).toHaveLength(0);
    expect(unchanged.messages.at(-1)?.text).toContain('変更していません');
    for (let index = 0; index < 40; index++) draft = reviseDraft(draft, index % 2 ? '青い配色に変更' : '緑の配色に変更');
    expect(draft.history).toHaveLength(10);
    expect(draft.messages).toHaveLength(30);
  });

  it('keeps revisions separate per app when switching between them', () => {
    const first = seedDraft('app-a', 'management-dashboard');
    const second = seedDraft('app-b', 'hello-web');
    saveDraft('app-a', reviseDraft(first, '部門別の表を追加'));
    expect(loadDraft('app-a', 'management-dashboard').config.departments).toBe(true);
    expect(loadDraft('app-b', 'hello-web')).toEqual(second);
  });

  it('round-trips only fixed preview data in the fragment, rejecting invalid/oversized configs', () => {
    const config = { ...defaultConfig('management-dashboard'), title: '<img src=x onerror=alert(1)>', trend: true };
    const url = previewLink(config);
    expect(url.split('#')[0]).toBe('/demo-preview.html');
    expect(parsePreviewConfig(url.slice(url.indexOf('#')))).toEqual(config);
    for (const hash of ['#broken', '#null', '#'+encodeURIComponent(JSON.stringify({ ...config, color: 'url(https://invalid.test)' })), '#'+ 'x'.repeat(4001)]) {
      expect(parsePreviewConfig(hash)).toEqual(defaultConfig('hello-web'));
    }
  });
});
