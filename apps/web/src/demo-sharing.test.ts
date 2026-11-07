import { describe, expect, it } from 'vitest';
import { createDemoSharing, recipientState } from './demo-sharing';
import { sandboxFixture } from './test/fixtures';

describe('browser-only sharing model', () => {
  it('grants/revokes fixed read-only members per app without leaking mutable state', () => {
    const sharing = createDemoSharing();
    expect(sharing.get('app-a')).toEqual([]);
    expect(sharing.save('app-a', ['member-b', 'member-a', 'member-a'])).toEqual(['member-a', 'member-b']);
    sharing.get('app-a').pop();
    expect(sharing.get('app-a')).toHaveLength(2);
    expect(sharing.get('app-b')).toEqual([]);
    sharing.save('app-a', []);
    expect(sharing.get('app-a')).toEqual([]);
    expect(createDemoSharing().get('app-a')).toEqual([]);
  });
  it('rejects unknown recipients without changing saved members', () => {
    const sharing = createDemoSharing();
    sharing.save('app-a', ['member-a']);
    expect(() => sharing.save('app-a', ['arbitrary-address'])).toThrow('デモのメンバー');
    expect(sharing.get('app-a')).toEqual(['member-a']);
  });
  it('shows content only for a saved recipient and a running, non-deleted app', () => {
    const running = { ...sandboxFixture, status: 'running' as const, desired_state: 'running' as const };
    expect(recipientState(running, [], 'member-a')).toBe('denied');
    expect(recipientState(running, ['member-a'], 'member-a')).toBe('ready');
    expect(recipientState(running, ['member-a'], 'member-b')).toBe('denied');
    expect(recipientState(sandboxFixture, ['member-a'], 'member-a')).toBe('stopped');
    expect(recipientState({ ...running, status: 'starting' }, ['member-a'], 'member-a')).toBe('starting');
    expect(recipientState({ ...running, status: 'failed' }, ['member-a'], 'member-a')).toBe('failed');
    expect(recipientState({ ...running, desired_state: 'deleted' }, ['member-a'], 'member-a')).toBe('deleting');
    expect(recipientState({ ...running, status: 'deleting' }, ['member-a'], 'member-a')).toBe('deleting');
    expect(recipientState({ ...running, desired_state: 'deleted', status: 'failed' }, ['member-a'], 'member-a')).toBe('failed');
    expect(recipientState({ ...running, status: 'deleted' }, ['member-a'], 'member-a')).toBe('deleted');
    expect(recipientState({ ...running, status: 'stopping' }, ['member-a'], 'member-a')).toBe('stopping');
  });
});
