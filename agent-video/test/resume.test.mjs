import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { access, link, mkdtemp, mkdir, readFile, symlink, unlink, writeFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { runJob, readJob } from '../src/jobs.mjs';
import { runBatch } from '../src/batch.mjs';
import { loadSegmentCache, resumeBatch, resumeJob } from '../src/resume.mjs';
import { probeMedia } from '../src/render.mjs';
import { withBatchLock } from '../src/execution-lock.mjs';

const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const key = 'a'.repeat(64);

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'agent-video-resume-'));
  const project = { version: 1, title: 'Original', canvas: { width: 160, height: 240, fps: 10 }, clips: [{ id: 'card', kind: 'color', color: '#000000', duration: 1 }] };
  const projectPath = join(root, 'project.json');
  await writeFile(projectPath, JSON.stringify(project));
  return { root, project, projectPath };
}

async function finish(loaded, { workDir }) {
  const file = join(workDir, 'render.mp4');
  await writeFile(file, loaded.project.title);
  return { file, duration: 1, width: 160, height: 240, fps: 10 };
}

async function partialJob(loaded) {
  let id;
  await assert.rejects(runJob(loaded, join(loaded.root, 'final.mp4'), {
    onProgress: value => { id = value.jobId; },
    render: async (_loaded, { workDir }) => {
      await writeFile(join(workDir, 'clip-0.mp4'), 'valid-segment');
      await writeFile(join(workDir, 'segments.json'), JSON.stringify({ version: 1, segments: [{ key, file: 'clip-0.mp4', sha256: digest('valid-segment'), bytes: 13 }] }));
      throw Object.assign(new Error('Interrupted composition'), { code: 'TOOL_FAILED' });
    },
  }), { code: 'TOOL_FAILED' });
  return id;
}

test('resumes a failed job from its saved project, retains anchors, and links a new job', async () => {
  const loaded = await fixture();
  loaded.project.words = [{ id: 'word', text: 'Original', start: 0, end: 0.8 }];
  loaded.project.captions = [{ fromWord: 'word', toWord: 'word' }];
  const id = await partialJob(loaded);
  await writeFile(loaded.projectPath, '{the live project changed');
  const resumed = await resumeJob(loaded.root, id, {
    render: async (snapshot, options) => {
      assert.equal(snapshot.root, loaded.root);
      assert.equal(snapshot.project.title, 'Original');
      assert.equal(snapshot.project.captions[0].fromWord, 'word');
      assert.equal(snapshot.project.captions[0].text, undefined);
      assert.equal(options.clipCache.get(key).sha256, digest('valid-segment'));
      return finish(snapshot, options);
    },
  });
  assert.equal(resumed.resumedFrom, id);
  assert.notEqual(resumed.id, id);
  assert.equal(resumed.status, 'succeeded');
  assert.equal(await readFile(join(loaded.root, 'final.mp4'), 'utf8'), 'Original');
  assert.equal((await readJob(loaded.root, id)).status, 'failed');
});

test('refuses existing requested outputs, but can use an explicit new filename', async () => {
  const loaded = await fixture();
  const id = await partialJob(loaded);
  await writeFile(join(loaded.root, 'final.mp4'), 'preserve');
  await assert.rejects(resumeJob(loaded.root, id, { render: () => assert.fail('must not render') }), { code: 'OUTPUT_EXISTS' });
  const result = await resumeJob(loaded.root, id, { output: join(loaded.root, 'second.mp4'), render: finish });
  assert.equal(result.status, 'succeeded');
  assert.equal(await readFile(join(loaded.root, 'final.mp4'), 'utf8'), 'preserve');
});

test('revalidates saved assets and supports interrupted running records without altering them', async () => {
  const loaded = await fixture();
  const id = await partialJob(loaded);
  const directory = join(loaded.root, '.agent-video', 'jobs', id);
  const record = await readJob(loaded.root, id);
  record.status = 'running';
  await writeFile(join(directory, 'job.json'), JSON.stringify(record));
  const resumed = await resumeJob(loaded.root, id, { render: finish });
  assert.equal(resumed.resumedFrom, id);
  assert.equal((await readJob(loaded.root, id)).status, 'running');
  const snapshot = JSON.parse(await readFile(join(directory, 'project.json'), 'utf8'));
  snapshot.clips = [{ id: 'image', kind: 'image', src: 'missing.png', duration: 1 }];
  await writeFile(join(directory, 'project.json'), JSON.stringify(snapshot));
  await assert.rejects(resumeJob(loaded.root, id, { output: join(loaded.root, 'third.mp4'), render: finish }), { code: 'INVALID_ASSET' });
});

test('segment metadata rejects unsafe paths/schema and ignores missing or corrupt segment bytes', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'agent-video-segments-'));
  const entry = { key, file: 'clip-0.mp4', sha256: digest('correct'), bytes: 7 };
  const save = segments => writeFile(join(directory, 'segments.json'), JSON.stringify({ version: 1, segments }));
  assert.equal((await loadSegmentCache(directory)).size, 0);
  for (const changed of [{ file: '../outside.mp4' }, { file: 'C:/outside.mp4' }, { key: 'bad' }, { key: [key] }, { sha256: [entry.sha256] }, { bytes: -1 }, { extra: true }]) {
    await save([{ ...entry, ...changed }]);
    await assert.rejects(loadSegmentCache(directory), { code: 'INVALID_SEGMENT_CACHE' });
  }
  await save([entry]);
  assert.equal((await loadSegmentCache(directory)).size, 0);
  await writeFile(join(directory, 'clip-0.mp4'), 'corrupt');
  assert.equal((await loadSegmentCache(directory)).size, 0);
  await writeFile(join(directory, 'clip-0.mp4'), 'correct');
  assert.equal((await loadSegmentCache(directory)).size, 1);
});

test('segment metadata cannot follow a symlink or junction outside its job', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'agent-video-segments-'));
  const outside = await mkdtemp(join(tmpdir(), 'agent-video-outside-'));
  const target = join(outside, 'file.mp4');
  await writeFile(target, 'outside');
  try { await symlink(process.platform === 'win32' ? outside : target, join(directory, 'clip-0.mp4'), process.platform === 'win32' ? 'junction' : 'file'); }
  catch (error) { if (error.code === 'EPERM') return t.skip('OS does not permit symlink creation'); throw error; }
  await writeFile(join(directory, 'segments.json'), JSON.stringify({ version: 1, segments: [{ key, file: 'clip-0.mp4', sha256: digest('outside'), bytes: 7 }] }));
  await assert.rejects(loadSegmentCache(directory), { code: 'INVALID_SEGMENT_CACHE' });
});

test('segment metadata enforces its byte and entry limits', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'agent-video-segments-'));
  const metadata = join(directory, 'segments.json');
  await writeFile(metadata, ' '.repeat(64 * 1024 + 1));
  await assert.rejects(loadSegmentCache(directory), { code: 'INVALID_SEGMENT_CACHE' });
  await writeFile(metadata, JSON.stringify({ version: 1, segments: new Array(101).fill({ key, file: 'clip-0.mp4', sha256: digest('a'), bytes: 1 }) }));
  await assert.rejects(loadSegmentCache(directory), { code: 'INVALID_SEGMENT_CACHE' });
});

test('resumes only unfinished batch variants from its immutable saved base', async () => {
  const loaded = await fixture();
  const directory = join(loaded.root, 'cuts');
  const original = await runBatch(loaded, [{ id: 'first', patch: { title: 'First' } }, { id: 'second', patch: { title: 'Second' } }], directory, {
    render: async (...args) => {
      if (args[0].project.title === 'Second') throw new Error('Temporary failure');
      return finish(...args);
    },
  });
  assert.equal(original.status, 'partial');
  await writeFile(loaded.projectPath, '{live source is no longer usable');
  const rendered = [];
  const resumed = await resumeBatch(directory, { render: async (...args) => { rendered.push(args[0].project.title); return finish(...args); } });
  assert.deepEqual(rendered, ['Second']);
  assert.equal(resumed.status, 'succeeded');
  assert.equal(resumed.variants[0].jobId, original.variants[0].jobId);
  assert.notEqual(resumed.variants[1].jobId, original.variants[1].jobId);
  assert.ok(resumed.variants[1].previousJobIds.includes(original.variants[1].jobId));
  assert.equal(await readFile(join(directory, 'first.mp4'), 'utf8'), 'First');
  assert.deepEqual(JSON.parse(await readFile(join(directory, 'batch.json'), 'utf8')), resumed);
});

test('a missing/corrupt successful batch output blocks resume and is never recreated implicitly', async () => {
  const loaded = await fixture();
  for (const mode of ['missing', 'corrupt']) {
    const directory = join(loaded.root, mode);
    await runBatch(loaded, [{ id: 'first', patch: {} }], directory, { render: finish });
    const output = join(directory, 'first.mp4');
    if (mode === 'missing') await unlink(output); else await writeFile(output, 'corrupt');
    await assert.rejects(resumeBatch(directory, { render: () => assert.fail('must not render') }), { code: 'BATCH_ARTIFACT_INVALID' });
    if (mode === 'missing') await assert.rejects(access(output), { code: 'ENOENT' });
    else assert.equal(await readFile(output, 'utf8'), 'corrupt');
  }
});

test('cancelled batch resume starts pending cuts and preserves its immutable base', async () => {
  const loaded = await fixture();
  const directory = join(loaded.root, 'cancelled');
  const controller = new AbortController();
  const original = await runBatch(loaded, [{ id: 'first', patch: { title: 'First' } }, { id: 'second', patch: { title: 'Second' } }], directory, {
    signal: controller.signal,
    render: async () => { controller.abort(); throw Object.assign(new Error('Cancelled'), { code: 'CANCELLED' }); },
  });
  assert.equal(original.status, 'cancelled');
  const resumed = await resumeBatch(directory, { render: finish });
  assert.equal(resumed.status, 'succeeded');
  assert.deepEqual(resumed.variants.map(entry => entry.status), ['succeeded', 'succeeded']);
  assert.ok(resumed.variants[0].previousJobIds.includes(original.variants[0].jobId));
  const base = join(directory, 'project.json');
  await writeFile(base, JSON.stringify({ ...loaded.project, title: 'Tampered snapshot' }));
  await assert.rejects(resumeBatch(directory, { render: () => assert.fail('must not render') }), { code: 'INVALID_BATCH_RECORD' });
});

test('a real failed composition resumes using its verified persisted FFmpeg segment', async () => {
  const loaded = await fixture();
  let id;
  await assert.rejects(runJob(loaded, join(loaded.root, 'real.mp4'), {
    onProgress(progress) {
      id = progress.jobId;
      if (progress.stage === 'compose' && progress.completed === 0) throw new Error('Stop after segment encoding');
    },
  }), /Stop after segment encoding/);
  const previousDirectory = join(loaded.root, '.agent-video', 'jobs', id);
  const metadata = JSON.parse(await readFile(join(previousDirectory, 'segments.json'), 'utf8'));
  assert.equal(metadata.segments.length, 1);
  assert.equal(metadata.segments[0].file, 'clip-0.mp4');
  await assert.rejects(access(join(loaded.root, 'real.mp4')), { code: 'ENOENT' });
  const resumed = await resumeJob(loaded.root, id);
  assert.equal(resumed.status, 'succeeded');
  assert.deepEqual(resumed.artifact.cache, { hits: 1, misses: 0 });
  assert.equal((await readJob(loaded.root, id)).status, 'failed');
  const output = await probeMedia(resumed.output);
  assert.equal(output.streams.find(stream => stream.codec_type === 'video').width, 160);
  assert.ok(Math.abs(Number(output.format.duration) - 1) < 0.15);
});

test('batch resume excludes concurrent execution and records the active new job before rendering', async () => {
  const loaded = await fixture();
  const directory = join(loaded.root, 'cuts');
  const original = await runBatch(loaded, [{ id: 'first', patch: {} }], directory, { render: async () => { throw new Error('Retry me'); } });
  let started;
  let release;
  const entered = new Promise(resolve => { started = resolve; });
  const paused = new Promise(resolve => { release = resolve; });
  const active = resumeBatch(directory, {
    render: async (...args) => { started(); await paused; return finish(...args); },
  });
  try {
    await entered;
    const record = JSON.parse(await readFile(join(directory, 'batch.json'), 'utf8'));
    assert.equal(record.variants[0].status, 'running');
    assert.match(record.variants[0].jobId, /^[a-f0-9-]{36}$/);
    assert.notEqual(record.variants[0].jobId, original.variants[0].jobId);
    assert.ok(record.variants[0].previousJobIds.includes(original.variants[0].jobId));
    await assert.rejects(resumeBatch(directory, { render: () => assert.fail('busy batch must not run') }), { code: 'BATCH_BUSY' });
  } finally { release(); }
  assert.equal((await active).status, 'succeeded');
  assert.equal((await resumeBatch(directory)).status, 'succeeded');
});

test('a running new batch also excludes resume attempts', async () => {
  const loaded = await fixture();
  const directory = join(loaded.root, 'new-cuts');
  let started;
  let release;
  const entered = new Promise(resolve => { started = resolve; });
  const paused = new Promise(resolve => { release = resolve; });
  const active = runBatch(loaded, [{ id: 'first', patch: {} }], directory, {
    render: async (...args) => { started(); await paused; return finish(...args); },
  });
  try {
    await entered;
    await assert.rejects(resumeBatch(directory), { code: 'BATCH_BUSY' });
  } finally { release(); }
  assert.equal((await active).status, 'succeeded');
});

test('state updates never follow planted links at old fixed temporary filenames', async () => {
  const loaded = await fixture();
  const directory = join(loaded.root, 'cuts');
  const jobTarget = join(loaded.root, 'preserve-job.txt');
  const batchTarget = join(loaded.root, 'preserve-batch.txt');
  await writeFile(jobTarget, 'keep job target');
  await writeFile(batchTarget, 'keep batch target');
  const batch = await runBatch(loaded, [{ id: 'first', patch: {} }], directory, {
    render: async (snapshot, options) => {
      await link(jobTarget, join(options.workDir, 'job.json.tmp'));
      await link(batchTarget, join(directory, 'batch.json.tmp'));
      await options.onProgress({ stage: 'clips', completed: 1, total: 1 });
      return finish(snapshot, options);
    },
  });
  assert.equal(batch.status, 'succeeded');
  assert.equal(await readFile(jobTarget, 'utf8'), 'keep job target');
  assert.equal(await readFile(batchTarget, 'utf8'), 'keep batch target');
});

test('the OS releases a batch lock when its owning process exits abruptly', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'agent-video-lock-'));
  const module = new URL('../src/execution-lock.mjs', import.meta.url).href;
  const script = `import { withBatchLock } from ${JSON.stringify(module)}; await withBatchLock(${JSON.stringify(directory)}, async () => { process.send('ready'); await new Promise(() => {}); });`;
  const child = spawn(process.execPath, ['--input-type=module', '-e', script], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe', 'ipc'] });
  let diagnostics = '';
  child.stderr.on('data', chunk => { diagnostics += chunk; });
  const closed = new Promise(resolve => child.once('close', resolve));
  try {
    await new Promise((resolve, reject) => {
      child.once('message', resolve);
      child.once('error', reject);
      child.once('exit', code => reject(new Error(`Lock process exited before ready (${code}): ${diagnostics}`)));
    });
    await assert.rejects(withBatchLock(directory, () => assert.fail('must stay excluded')), { code: 'BATCH_BUSY' });
  } finally { child.kill(); await closed; }
  assert.equal(await withBatchLock(directory, () => 'released'), 'released');
});
