import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

async function login(page: Page, email: string) {
  await page.getByLabel('メールアドレス', { exact: true }).fill(email);
  const response = page.waitForResponse(response => response.url().endsWith('/api/v1/auth/login') && response.request().method() === 'POST');
  const listResponse = page.waitForResponse(response => response.url().endsWith('/api/v1/sandboxes') && response.request().method() === 'GET');
  await page.getByRole('button', { name: '開発用ログイン', exact: true }).click();
  const session = await (await response).json() as { token: string };
  await expect(page.getByRole('button', { name: 'ログアウト', exact: true })).toBeVisible();
  expect((await listResponse).ok()).toBeTruthy();
  await expect(page.getByTestId('runtime-banner')).toContainText(/real|kind/i);
  return { Authorization: `Bearer ${session.token}` };
}

test('real UI lifecycle and independent applications', async ({ page, context }) => {
  await page.goto('/');
  const auth = await login(page, 'browser-lifecycle@example.test');
  await expect(page.getByTestId('runtime-banner')).toContainText(/real|kind/i);
  const names = [`Browser A ${Date.now()}`, `Browser B ${Date.now()}`];
  const ids: string[] = [];
  for (const name of names) {
    await page.getByRole('button', { name: 'サンプルを登録', exact: true }).first().click();
    const dialog = page.getByRole('dialog', { name: 'サンプルアプリを登録' });
    await dialog.getByLabel('アプリ名', { exact: true }).fill(name);
    await dialog.getByLabel('自動停止までの時間（秒）', { exact: true }).fill('900');
    await dialog.getByRole('button', { name: '登録', exact: true }).click();
    const row = page.getByRole('button', { name: `${name} の詳細`, exact: true });
    await row.click();
    const id = await row.getAttribute('data-sandbox-id');
    expect(id).toBeTruthy();
    ids.push(id!);
    await page.getByTestId('sandbox-detail').getByRole('button', { name: '起動', exact: true }).click();
    await expect(page.getByTestId('sandbox-detail').getByTestId('sandbox-status')).toHaveText('Ready');
    const href = await page.getByRole('link', { name: 'アプリを開く', exact: true }).getAttribute('href');
    expect(href).toContain(id!);
    const sample = await context.newPage();
    await sample.goto(href!);
    await expect(sample.getByRole('heading', { name: 'Hello ProtoHub' })).toBeVisible();
    await sample.getByRole('button', { name: 'Clicked 0 times' }).click();
    await expect(sample.getByRole('button', { name: 'Clicked 1 times' })).toBeVisible();
    await sample.close();
  }
  await page.getByRole('button', { name: `${names[0]} の詳細`, exact: true }).click();
  await page.getByTestId('sandbox-detail').getByRole('button', { name: '停止', exact: true }).click();
  await expect(page.getByTestId('sandbox-detail').getByTestId('sandbox-status')).toHaveText('停止中');
  await expect(page.getByRole('link', { name: 'アプリを開く', exact: true })).toHaveCount(0);
  const responseB = await page.request.get(`/api/v1/sandboxes/${ids[1]}`, { headers: auth });
  const appB = await responseB.json();
  expect(appB.status).toBe('running');
  expect((await page.request.get(appB.preview_url)).ok()).toBeTruthy();
  await page.getByTestId('sandbox-detail').getByRole('button', { name: '起動', exact: true }).click();
  await expect(page.getByTestId('sandbox-detail').getByTestId('sandbox-status')).toHaveText('Ready');
  for (let index = 0; index < names.length; index++) {
    await page.getByRole('button', { name: `${names[index]} の詳細`, exact: true }).click();
    await page.getByTestId('sandbox-detail').getByRole('button', { name: '削除', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'アプリを削除' });
    await expect(dialog).toContainText(names[index]);
    await dialog.getByRole('button', { name: '削除する', exact: true }).click();
    await expect.poll(async () => (await (await page.request.get(`/api/v1/sandboxes/${ids[index]}`, { headers: auth })).json()).status).toBe('deleted');
    await expect(page.getByRole('button', { name: `${names[index]} の詳細`, exact: true })).toHaveCount(0);
  }
});


test('development users see owned and explicitly shared apps across login changes', async ({ page }, testInfo) => {
  await page.goto('/');
  await page.screenshot({ path: testInfo.outputPath('development-login.png'), fullPage: true });
  await login(page, 'browser-owner@example.test');
  const suffix = Date.now();
  const sharedName = `Shared browser ${suffix}`;
  const privateName = `Private browser ${suffix}`;
  const ownedIds: string[] = [];
  try {
    for (const name of [sharedName, privateName]) {
      await page.getByRole('button', { name: 'サンプルを登録', exact: true }).first().click();
      const dialog = page.getByRole('dialog', { name: 'サンプルアプリを登録' });
      await dialog.getByLabel('アプリ名', { exact: true }).fill(name);
      await dialog.getByRole('button', { name: '登録', exact: true }).click();
      const row = page.getByRole('button', { name: `${name} の詳細`, exact: true });
      await expect(row).toBeVisible();
      const id = await row.getAttribute('data-sandbox-id');
      expect(id).toBeTruthy();
      ownedIds.push(id!);
    }
    await page.getByRole('button', { name: `${sharedName} の詳細`, exact: true }).click();
    await page.screenshot({ path: testInfo.outputPath('owner-workspace.png'), fullPage: true });
    await page.getByRole('button', { name: '共有設定', exact: true }).click();
    const sharing = page.getByRole('dialog', { name: 'アプリの共有', exact: true });
    await sharing.getByLabel('共有先のメールアドレス', { exact: true }).fill('browser-reader@example.test');
    await page.screenshot({ path: testInfo.outputPath('share-editor.png'), fullPage: true });
    await sharing.getByRole('button', { name: '共有を保存', exact: true }).click();
    await expect(sharing).toBeHidden();
    await page.getByRole('button', { name: 'ログアウト', exact: true }).click();
    await login(page, 'browser-reader@example.test');
    await expect(page.getByRole('button', { name: `${sharedName} の詳細`, exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: `${privateName} の詳細`, exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: `${sharedName} の詳細`, exact: true }).click();
    await expect(page.getByRole('button', { name: '共有設定', exact: true })).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath('recipient-workspace.png'), fullPage: true });
    for (const name of ['起動', '停止', '削除']) {
      const button = page.getByTestId('sandbox-detail').getByRole('button', { name, exact: true });
      if (await button.count()) await expect(button).toBeDisabled();
    }
    await page.reload();
    await expect(page.getByRole('button', { name: `${sharedName} の詳細`, exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'ログアウト', exact: true }).click();
    await login(page, 'browser-outsider@example.test');
    await expect(page.getByRole('button', { name: `${sharedName} の詳細`, exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: `${privateName} の詳細`, exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: 'ログアウト', exact: true }).click();
    await login(page, 'browser-owner@example.test');
    await page.getByRole('button', { name: `${sharedName} の詳細`, exact: true }).click();
    await page.getByRole('button', { name: '共有設定', exact: true }).click();
    await sharing.getByLabel('共有先のメールアドレス', { exact: true }).fill('');
    await sharing.getByRole('button', { name: '共有を保存', exact: true }).click();
    await expect(sharing).toBeHidden();
    await page.getByRole('button', { name: 'ログアウト', exact: true }).click();
    await login(page, 'browser-reader@example.test');
    await expect(page.getByRole('button', { name: `${sharedName} の詳細`, exact: true })).toHaveCount(0);
  } finally {
    const cleanupLogin = await page.request.post('/api/v1/auth/login', {
      headers: { 'X-ProtoHub-Client': 'console' }, data: { email: 'browser-owner@example.test' },
    });
    expect(cleanupLogin.ok()).toBeTruthy();
    const cleanupSession = await cleanupLogin.json() as { token: string };
    const owner = { Authorization: `Bearer ${cleanupSession.token}` };
    for (const id of ownedIds) {
      const response = await page.request.delete(`/api/v1/sandboxes/${id}`, {
        headers: { ...owner, 'X-ProtoHub-Client': 'console' }, data: {},
      });
      expect(response.status()).toBe(202);
      await expect.poll(async () => (await (await page.request.get(`/api/v1/sandboxes/${id}`, { headers: owner })).json()).status).toBe('deleted');
    }
  }
});
