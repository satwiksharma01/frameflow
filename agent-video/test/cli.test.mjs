import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, readFile, writeFile, access } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import test from 'node:test';
import { probeMedia } from '../src/render.mjs';

const exec = promisify(execFile);
const cli = fileURLToPath(new URL('../bin/agent-video.mjs', import.meta.url));
async function call(args, cwd) {
  try { const result = await exec(process.execPath, [cli, ...args, '--json'], { cwd, windowsHide: true }); return { code: 0, ...result, data: JSON.parse(result.stdout) }; }
  catch (error) { return { code: error.code, stdout: error.stdout, stderr: error.stderr, data: JSON.parse(error.stdout) }; }
}

test('an agent can initialize, check, and plan a project without render tools', async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'agent-video-cli-'));
  const created = await call(['init', 'demo'], cwd);
  assert.equal(created.code, 0, created.stderr);
  const checked = await call(['check', 'demo/project.json'], cwd);
  assert.equal(checked.data.ok, true);
  assert.equal(checked.data.duration, 6);
  const plan = await call(['plan', 'demo/project.json'], cwd);
  assert.equal(plan.data.clips.length, 3);
  assert.equal(plan.data.clips[1].start, 2);
  assert.equal(plan.data.clips[2].end, 6);
  await assert.rejects(access(join(cwd, 'demo', '.agent-video')), { code: 'ENOENT' });
});

test('initialization never overwrites a project', async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'agent-video-cli-'));
  await call(['init', 'demo'], cwd);
  const file = join(cwd, 'demo', 'project.json');
  const original = await readFile(file, 'utf8');
  const again = await call(['init', 'demo'], cwd);
  assert.equal(again.data.error.code, 'OUTPUT_EXISTS');
  assert.equal(await readFile(file, 'utf8'), original);
});

test('variant replaces requested fields and leaves the original intact', async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'agent-video-cli-'));
  await call(['init', 'demo'], cwd);
  await writeFile(join(cwd, 'changes.json'), JSON.stringify({ title: 'Second cut', captions: [{ text: 'Different words', start: 0, end: 2 }] }));
  const result = await call(['variant', 'demo/project.json', '--patch', 'changes.json', '--out', 'demo/second.json'], cwd);
  assert.equal(result.code, 0, result.stderr);
  const second = JSON.parse(await readFile(join(cwd, 'demo', 'second.json'), 'utf8'));
  assert.equal(second.title, 'Second cut');
  assert.equal(second.captions[0].text, 'Different words');
  assert.equal(second.clips.length, 3);
  assert.notEqual(JSON.parse(await readFile(join(cwd, 'demo', 'project.json'), 'utf8')).title, 'Second cut');
  assert.equal((await call(['check', 'demo/second.json'], cwd)).code, 0);
});

test('bad manifests and usage have machine-readable nonzero failures', async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'agent-video-cli-'));
  await writeFile(join(cwd, 'bad.json'), '{oops');
  const bad = await call(['check', 'bad.json'], cwd);
  assert.equal(bad.code, 1);
  assert.equal(bad.data.error.code, 'INVALID_PROJECT');
  const unknown = await call(['check', 'bad.json', '--force'], cwd);
  assert.equal(unknown.code, 2);
  assert.equal(unknown.data.error.code, 'USAGE_ERROR');
});

test('a variant rejects unknown patch fields and cannot move away from its assets', async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'agent-video-cli-'));
  await call(['init', 'demo'], cwd);
  await writeFile(join(cwd, 'changes.json'), JSON.stringify({ captionz: [] }));
  const bad = await call(['variant', 'demo/project.json', '--patch', 'changes.json', '--out', 'demo/bad.json'], cwd);
  assert.equal(bad.data.error.code, 'INVALID_PROJECT');
  await assert.rejects(access(join(cwd, 'demo', 'bad.json')), { code: 'ENOENT' });
  await writeFile(join(cwd, 'changes.json'), JSON.stringify({ title: 'Second' }));
  const moved = await call(['variant', 'demo/project.json', '--patch', 'changes.json', '--out', 'elsewhere.json'], cwd);
  assert.equal(moved.data.error.code, 'INVALID_VARIANT_PATH');
});

test('the CLI renders a playable video, exposes its status, and preserves an existing output', async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'agent-video-cli-render-'));
  await call(['init', 'demo'], cwd);
  const file = join(cwd, 'demo', 'project.json');
  const project = JSON.parse(await readFile(file, 'utf8'));
  project.canvas = { width: 160, height: 240, fps: 10 };
  project.clips = [{ id: 'card', kind: 'color', color: '#123456', duration: 0.5 }];
  project.captions = [{ text: 'Made locally', start: 0, end: 0.5, fontSize: 16 }];
  await writeFile(file, JSON.stringify(project));
  const result = await call(['render', 'demo/project.json', '--out', 'final.mp4'], cwd);
  assert.equal(result.code, 0, JSON.stringify(result.data));
  assert.equal(result.data.job.status, 'succeeded');
  assert.match(result.stderr, /compose/);
  const metadata = await probeMedia(join(cwd, 'final.mp4'));
  assert.equal(metadata.streams.find(stream => stream.codec_type === 'video').width, 160);
  const saved = await call(['status', 'demo/project.json', '--job', result.data.job.id], cwd);
  assert.equal(saved.data.job.artifact.sha256, result.data.job.artifact.sha256);
  const first = await readFile(join(cwd, 'final.mp4'));
  const again = await call(['render', 'demo/project.json', '--out', 'final.mp4'], cwd);
  assert.equal(again.data.error.code, 'OUTPUT_EXISTS');
  assert.deepEqual(await readFile(join(cwd, 'final.mp4')), first);
});

test('imports supplied word timings, preserves anchors, and exposes retimed captions in the plan', async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'agent-video-cli-words-'));
  await call(['init', 'demo'], cwd);
  const words = Array.from({ length: 5 }, (_, index) => ({ id: `w${index}`, text: `word${index}`, start: index * 0.3, end: index * 0.3 + 0.2 }));
  await writeFile(join(cwd, 'words.json'), JSON.stringify(words));
  const imported = await call(['captions', 'demo/project.json', '--words', 'words.json', '--group-size', '2', '--out', 'demo/timed.json'], cwd);
  assert.equal(imported.code, 0, JSON.stringify(imported.data));
  const saved = JSON.parse(await readFile(join(cwd, 'demo', 'timed.json'), 'utf8'));
  assert.equal(saved.captions.length, 3);
  assert.equal(saved.captions[0].fromWord, 'w0');
  assert.equal(saved.captions[0].start, undefined);
  assert.equal(saved.captions[0].text, undefined);
  const before = await call(['plan', 'demo/timed.json'], cwd);
  assert.equal(before.data.wordCount, 5);
  assert.equal(before.data.captions[0].text, 'word0 word1');
  assert.equal(before.data.captions[0].start, 0);
  await writeFile(join(cwd, 'retime.json'), JSON.stringify({ words: words.map(word => ({ ...word, start: word.start + 1, end: word.end + 1 })) }));
  assert.equal((await call(['variant', 'demo/timed.json', '--patch', 'retime.json', '--out', 'demo/retimed.json'], cwd)).code, 0);
  const after = await call(['plan', 'demo/retimed.json'], cwd);
  assert.equal(after.data.captions[0].start, 1);
  assert.equal(after.data.captions[0].end, 1.5);
});

test('batch CLI renders distinct outputs and reports unchanged clip reuse', async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'agent-video-cli-batch-'));
  await call(['init', 'demo'], cwd);
  const projectPath = join(cwd, 'demo', 'project.json');
  const project = JSON.parse(await readFile(projectPath, 'utf8'));
  project.canvas = { width: 160, height: 240, fps: 10 };
  project.clips = [{ id: 'card', kind: 'color', color: '#123456', duration: 0.4 }];
  project.captions = [];
  await writeFile(projectPath, JSON.stringify(project));
  await writeFile(join(cwd, 'variants.json'), JSON.stringify(['A', 'B'].map(id => ({ id, patch: { captions: [{ text: id, start: 0, end: 0.4, fontSize: 16 }] } }))));
  const result = await call(['batch', 'demo/project.json', '--variants', 'variants.json', '--out-dir', 'cuts'], cwd);
  assert.equal(result.code, 0, JSON.stringify(result.data));
  assert.equal(result.data.batch.status, 'succeeded');
  assert.equal(result.data.batch.variants[1].artifact.cache.hits, 1);
  assert.equal((await probeMedia(join(cwd, 'cuts', 'B.mp4'))).streams.find(stream => stream.codec_type === 'video').width, 160);
  assert.notDeepEqual(await readFile(join(cwd, 'cuts', 'A.mp4')), await readFile(join(cwd, 'cuts', 'B.mp4')));
  const again = await call(['batch', 'demo/project.json', '--variants', 'variants.json', '--out-dir', 'cuts'], cwd);
  assert.equal(again.data.error.code, 'OUTPUT_EXISTS');
});

test('batch CLI returns a nonzero partial result while preserving successful cuts', async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'agent-video-cli-partial-'));
  await call(['init', 'demo'], cwd);
  await writeFile(join(cwd, 'demo', 'assets', 'fake.png'), 'not an image');
  await writeFile(join(cwd, 'variants.json'), JSON.stringify([
    { id: 'bad', patch: { clips: [{ id: 'fake', kind: 'image', src: 'assets/fake.png', duration: 6 }] } },
    { id: 'good', patch: { canvas: { width: 160, height: 240, fps: 10 }, captions: [] } },
  ]));
  const result = await call(['batch', 'demo/project.json', '--variants', 'variants.json', '--out-dir', 'cuts'], cwd);
  assert.equal(result.code, 1);
  assert.equal(result.data.ok, false);
  assert.equal(result.data.error.code, 'BATCH_FAILED');
  assert.equal(result.data.batch.status, 'partial');
  assert.equal(result.data.batch.variants[1].status, 'succeeded');
  await access(join(cwd, 'cuts', 'good.mp4'));
  await assert.rejects(access(join(cwd, 'cuts', 'bad.mp4')), { code: 'ENOENT' });
});
