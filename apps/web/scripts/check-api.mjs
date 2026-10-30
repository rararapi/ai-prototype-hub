import { readFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';

const directory = await mkdtemp(join(tmpdir(), 'protohub-contract-'));
try {
  const generated = join(directory, 'api.d.ts');
  const result = spawnSync(process.execPath, [
    'node_modules/openapi-typescript/bin/cli.js', '../../contracts/openapi.yaml', '-o', generated,
  ], { stdio: 'inherit', shell: false });
  if (result.status !== 0) process.exitCode = 1;
  else {
    const expected = await readFile('src/generated/api.d.ts', 'utf8');
    const actual = await readFile(generated, 'utf8');
    if (expected !== actual) {
      console.error('FAIL frontend API types differ from the canonical contract; run npm run generate:api.');
      process.exitCode = 1;
    } else console.log('PASS frontend generated API types match canonical contract');
  }
} finally {
  await rm(directory, { recursive: true, force: true });
}
