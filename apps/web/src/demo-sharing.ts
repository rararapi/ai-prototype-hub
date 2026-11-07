import type { Sandbox } from './api';

export const DEMO_MEMBERS = [
  { id: 'member-a', name: 'メンバーA' },
  { id: 'member-b', name: 'メンバーB' },
] as const;
export type DemoMemberId = typeof DEMO_MEMBERS[number]['id'];
export function createDemoSharing() {
  const shared = new Map<string, DemoMemberId[]>();
  return {
    get(id: string): DemoMemberId[] { return [...(shared.get(id) ?? [])]; },
    save(id: string, members: readonly string[]): DemoMemberId[] {
      if (members.some(member => !DEMO_MEMBERS.some(known => known.id === member))) {
        throw new Error('デモのメンバーを選択してください。');
      }
      const next = DEMO_MEMBERS.filter(member => members.includes(member.id)).map(member => member.id);
      shared.set(id, next);
      return [...next];
    },
  };
}
export const demoSharing = createDemoSharing();

export function recipientState(sandbox: Sandbox, members: readonly DemoMemberId[], viewer: DemoMemberId) {
  if (sandbox.status === 'deleted') return 'deleted';
  if (sandbox.desired_state === 'deleted' || sandbox.status === 'deleting') return sandbox.status === 'failed' ? 'failed' : 'deleting';
  if (!members.includes(viewer)) return 'denied';
  if (sandbox.status === 'running') return 'ready';
  if (sandbox.status === 'starting') return 'starting';
  if (sandbox.status === 'stopping') return 'stopping';
  if (sandbox.status === 'failed') return 'failed';
  return 'stopped';
}
