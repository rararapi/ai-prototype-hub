import { test, expect } from '@playwright/test';

test('real UI lifecycle and independent applications', async ({ page, context }) => {
  await page.goto('/');
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
  const responseB = await page.request.get(`/api/v1/sandboxes/${ids[1]}`);
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
    await expect.poll(async () => (await (await page.request.get(`/api/v1/sandboxes/${ids[index]}`)).json()).status).toBe('deleted');
    await expect(page.getByRole('button', { name: `${names[index]} の詳細`, exact: true })).toHaveCount(0);
  }
});
