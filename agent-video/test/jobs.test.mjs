import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { readJob, runJob } from '../src/jobs.mjs';

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'agent-video-job-'));
  const project = { version: 1, title: 'Test', canvas: { width: 320, height: 240, fps: 24 }, clips: [{ id: 'a', kind: 'color', color: '#000000', duration: 1 }], captions: [], audio: [] };
  return { project, projectPath: join(root, 'project.json'), root };
}

test('publishes a completed render and records inspectable job state', async () => {
  const loaded = await fixture();
  const output = join(loaded.root, 'out', 'video.mp4');
  const job = await runJob(loaded, output, {
    render: async (_loaded, { workDir, onProgress }) => {
      await onProgress({ stage: 'clips', completed: 1, total: 1 });
      const file = join(workDir, 'render.mp4');
      await writeFile(file, 'rendered-video');
      return { file, duration: 1, width: 320, height: 240, fps: 24 };
    },
  });
  assert.equal(job.status, 'succeeded');
  assert.equal(await readFile(output, 'utf8'), 'rendered-video');
  assert.equal(job.artifact.bytes, 14);
  assert.match(job.artifact.sha256, /^[a-f0-9]{64}$/);
  assert.deepEqual(await readJob(loaded.root, job.id), job);
  assert.equal(JSON.parse(await readFile(join(loaded.root, '.agent-video', 'jobs', job.id, 'project.json'), 'utf8')).title, 'Test');
});

test('an existing output is never overwritten or rendered', async () => {
  const loaded = await fixture();
  const output = join(loaded.root, 'original.mp4');
  await writeFile(output, 'keep');
  await assert.rejects(runJob(loaded, output, { render: () => assert.fail('must not run') }), { code: 'OUTPUT_EXISTS' });
  assert.equal(await readFile(output, 'utf8'), 'keep');
});

test('failed renders retain their error and publish no video', async () => {
  const loaded = await fixture();
  const output = join(loaded.root, 'failed.mp4');
  let id;
  await assert.rejects(runJob(loaded, output, {
    onProgress: event => { id = event.jobId; },
    render: async () => { throw Object.assign(new Error('A selected clip is too short'), { code: 'INVALID_MEDIA' }); },
  }), error => error.code === 'INVALID_MEDIA' && Boolean(error.jobId));
  const job = await readJob(loaded.root, id);
  assert.equal(job.status, 'failed');
  assert.equal(job.error.code, 'INVALID_MEDIA');
  await assert.rejects(readFile(output), { code: 'ENOENT' });
});

test('publication refuses an output created while the renderer is working', async () => {
  const loaded = await fixture();
  const output = join(loaded.root, 'race.mp4');
  await assert.rejects(runJob(loaded, output, {
    render: async (_loaded, { workDir }) => {
      const file = join(workDir, 'render.mp4');
      await writeFile(file, 'new');
      await writeFile(output, 'winner');
      return { file, duration: 1, width: 320, height: 240, fps: 24 };
    },
  }), { code: 'OUTPUT_EXISTS' });
  assert.equal(await readFile(output, 'utf8'), 'winner');
});

test('job lookup rejects traversal identifiers', async () => {
  const loaded = await fixture();
  await assert.rejects(readJob(loaded.root, '../project'), { code: 'INVALID_JOB_ID' });
});

test('job storage cannot escape through a symlink', async t => {
  const loaded = await fixture();
  const outside = await mkdtemp(join(tmpdir(), 'agent-video-outside-'));
  try { await symlink(outside, join(loaded.root, '.agent-video'), process.platform === 'win32' ? 'junction' : 'dir'); }
  catch (error) { if (error.code === 'EPERM') return t.skip('OS does not permit symlink creation'); throw error; }
  await assert.rejects(runJob(loaded, join(loaded.root, 'escape.mp4'), { render: () => assert.fail('must not run') }), { code: 'INVALID_JOB_STORAGE' });
  await assert.rejects(readFile(join(outside, 'jobs')), { code: 'ENOENT' });
});
