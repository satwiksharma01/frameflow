import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import test from 'node:test';

const exec = promisify(execFile);
const cli = fileURLToPath(new URL('../bin/agent-video.mjs', import.meta.url));
async function call(args, cwd) {
  try {
    const result = await exec(process.execPath, [cli, ...args, '--json'], { cwd, windowsHide: true });
    return { code: 0, data: JSON.parse(result.stdout) };
  } catch (error) { return { code: error.code, data: JSON.parse(error.stdout) }; }
}

test('help exposes the reference workflow and strict command options', async () => {
  const result = await call(['help']);
  for (const command of ['reference-prepare', 'reference-check', 'reference-sample', 'frameflow-export', 'frameflow-check']) {
    assert.ok(result.data.help.includes(command), `${command} missing from help`);
  }
  for (const args of [['reference-prepare', 'source.mp4'], ['frameflow-export', 'session'], ['reference-sample', 'session']]) {
    const invalid = await call(args);
    assert.equal(invalid.code, 2);
    assert.equal(invalid.data.error.code, 'USAGE_ERROR');
  }
});

test('a future caller can validate Frameflow documents without rendering or invoking Frameflow', async () => {
  const root = await mkdtemp(join(tmpdir(), 'agent-video-contract-cli-'));
  const board = { script: 'A title.', scenes: [{ visual: { type: 'title', text: 'A title' }, duration: 2, reason: 'Opening title' }] };
  const brief = { title: 'Contract', format: 'reel', aspect: '9:16', target_seconds: 2, audience: 'creators', tone: 'direct', summary: 'A short title.' };
  for (const [name, value] of Object.entries({ board, brief, inputs: { footage: [], assets: [], music: [] } })) {
    await writeFile(join(root, `${name}.json`), JSON.stringify(value));
  }
  const files = ['board.json', 'brief.json', 'inputs.json'];
  const before = await Promise.all(files.map(file => readFile(join(root, file), 'utf8')));
  const result = await call(['frameflow-check', 'board.json', '--brief', 'brief.json', '--inputs', 'inputs.json'], root);
  assert.equal(result.code, 0, JSON.stringify(result.data));
  assert.equal(result.data.ok, true);
  assert.equal(result.data.duration, 2);
  assert.equal(result.data.timeline[0].start, 0);
  assert.deepEqual(await Promise.all(files.map(file => readFile(join(root, file), 'utf8'))), before);
  await writeFile(join(root, 'board.json'), JSON.stringify({ ...board, voice: 'generated' }));
  const generation = await call(['frameflow-check', 'board.json', '--brief', 'brief.json', '--inputs', 'inputs.json'], root);
  assert.equal(generation.code, 1);
  assert.equal(generation.data.ok, false);
});
