import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, access } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { runBatch } from '../src/batch.mjs';
import { validateProject } from '../src/project.mjs';

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'agent-video-batch-'));
  const project = validateProject({ version: 1, title: 'Original', canvas: { width: 160, height: 240, fps: 10 }, clips: [{ id: 'card', kind: 'color', color: '#000000', duration: 1 }] });
  const projectPath = join(root, 'project.json');
  await writeFile(projectPath, JSON.stringify(project));
  return { root, project, projectPath };
}

async function render(loaded, { workDir, clipCache }) {
  const file = join(workDir, 'render.mp4');
  await writeFile(file, loaded.project.title);
  const reused = clipCache.has('test');
  clipCache.set('test', file);
  return { file, duration: 1, width: 160, height: 240, fps: 10, cache: { hits: reused ? 1 : 0, misses: reused ? 0 : 1 } };
}

test('renders each variant with its patch, shared clip cache, and inspectable manifest', async () => {
  const loaded = await fixture();
  const outDir = join(loaded.root, 'batch');
  const batch = await runBatch(loaded, [{ id: 'first', patch: { title: 'First' } }, { id: 'second', patch: { title: 'Second' } }], outDir, { render });
  assert.equal(batch.status, 'succeeded');
  assert.equal(await readFile(join(outDir, 'first.mp4'), 'utf8'), 'First');
  assert.equal(await readFile(join(outDir, 'second.mp4'), 'utf8'), 'Second');
  assert.equal(batch.variants[1].artifact.cache.hits, 1);
  assert.match(batch.variants[0].jobId, /^[a-f0-9-]{36}$/);
  assert.deepEqual(JSON.parse(await readFile(join(outDir, 'batch.json'), 'utf8')), batch);
  assert.equal(loaded.project.title, 'Original');
});

test('preflights all projects and assets before creating any output', async () => {
  const loaded = await fixture();
  const outDir = join(loaded.root, 'invalid');
  await assert.rejects(runBatch(loaded, [
    { id: 'good', patch: { title: 'Fine' } },
    { id: 'bad', patch: { clips: [{ id: 'missing', kind: 'image', src: 'missing.png', duration: 1 }] } },
  ], outDir, { render: () => assert.fail('preflight must finish before rendering') }), { code: 'INVALID_ASSET' });
  await assert.rejects(access(outDir), { code: 'ENOENT' });
});

test('refuses existing output directories and unsafe or duplicate output IDs', async () => {
  const loaded = await fixture();
  await assert.rejects(runBatch(loaded, [{ id: 'a', patch: {} }], loaded.root, { render }), { code: 'OUTPUT_EXISTS' });
  const malformed = [[], [{ id: 'CON', patch: {} }], [{ id: '../a', patch: {} }], [{ id: 'A', patch: {} }, { id: 'a', patch: {} }], [{ id: 'a', patch: [], extra: true }], [{ id: 'a', patch: { unknown: 1 } }]];
  for (const variants of malformed) {
    await assert.rejects(runBatch(loaded, variants, join(loaded.root, 'bad'), { render }), error => ['INVALID_BATCH', 'INVALID_PROJECT'].includes(error.code));
  }
});

test('records a failed render and continues with the remaining variants', async () => {
  const loaded = await fixture();
  const outDir = join(loaded.root, 'partial');
  const batch = await runBatch(loaded, [{ id: 'bad', patch: { title: 'Bad' } }, { id: 'good', patch: { title: 'Good' } }], outDir, {
    render: async (...args) => {
      if (args[0].project.title === 'Bad') throw Object.assign(new Error('Unsupported material'), { code: 'INVALID_MEDIA' });
      return render(...args);
    },
  });
  assert.equal(batch.status, 'partial');
  assert.equal(batch.variants[0].status, 'failed');
  assert.equal(batch.variants[0].error.code, 'INVALID_MEDIA');
  assert.equal(batch.variants[1].status, 'succeeded');
  await assert.rejects(access(join(outDir, 'bad.mp4')), { code: 'ENOENT' });
  assert.equal(await readFile(join(outDir, 'good.mp4'), 'utf8'), 'Good');
});

test('cancellation stops the current job and marks remaining variants cancelled', async () => {
  const loaded = await fixture();
  const controller = new AbortController();
  const outDir = join(loaded.root, 'cancelled');
  let calls = 0;
  const batch = await runBatch(loaded, [{ id: 'first', patch: {} }, { id: 'second', patch: {} }], outDir, {
    signal: controller.signal,
    render: async () => { calls++; controller.abort(); throw Object.assign(new Error('Cancelled'), { code: 'CANCELLED' }); },
  });
  assert.equal(calls, 1);
  assert.equal(batch.status, 'cancelled');
  assert.deepEqual(batch.variants.map(variant => variant.status), ['cancelled', 'cancelled']);
  assert.deepEqual(JSON.parse(await readFile(join(outDir, 'batch.json'), 'utf8')), batch);
});
