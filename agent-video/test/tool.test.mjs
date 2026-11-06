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
async function call(args, cwd, overrides = {}) {
  try {
    const result = await exec(process.execPath, [cli, ...args, '--json'], { cwd, env: { ...process.env, ...overrides }, windowsHide: true });
    return { code: 0, ...result, data: JSON.parse(result.stdout) };
  } catch (error) { return { code: error.code, stderr: error.stderr, data: JSON.parse(error.stdout) }; }
}
async function source(cwd) {
  const file = join(cwd, 'reference.mp4');
  await exec(process.env.FFMPEG_PATH || 'ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=160x240:r=10:d=0.3', '-f', 'lavfi', '-i', 'color=c=blue:s=160x240:r=10:d=0.3', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=0.6', '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[v]', '-map', '[v]', '-map', '2:a', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', file], { windowsHide: true });
  return file;
}

test('CLI inspects real source evidence and reconstructs an editable project with audio', async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'agent-video-tool-'));
  await source(cwd);
  const inspected = await call(['inspect', 'reference.mp4', '--out-dir', 'evidence'], cwd);
  assert.equal(inspected.code, 0, JSON.stringify(inspected.data));
  assert.equal(inspected.data.inspection.hasVideo, true);
  assert.equal(inspected.data.inspection.hasAudio, true);
  assert.equal(inspected.data.inspection.width, 160);
  assert.ok(inspected.data.inspection.frames.length > 0);
  await readFile(inspected.data.inspection.contactSheet);
  const rebuilt = await call(['reconstruct', 'reference.mp4', '--out-dir', 'editable'], cwd);
  assert.equal(rebuilt.code, 0, JSON.stringify(rebuilt.data));
  const project = JSON.parse(await readFile(rebuilt.data.project, 'utf8'));
  assert.ok(project.clips.length >= 1);
  assert.equal(project.clips[0].kind, 'video');
  assert.equal(project.clips[0].volume, 1);
  assert.equal((await call(['check', 'editable/project.json'], cwd)).code, 0);
  const again = await call(['reconstruct', 'reference.mp4', '--out-dir', 'editable'], cwd);
  assert.equal(again.data.error.code, 'OUTPUT_EXISTS');
});

test('CLI resumes a failed render as a new job and leaves the failed record intact', async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'agent-video-tool-resume-'));
  await call(['init', 'demo'], cwd);
  const file = join(cwd, 'demo', 'project.json');
  const project = JSON.parse(await readFile(file, 'utf8'));
  project.canvas = { width: 160, height: 240, fps: 10 };
  project.clips = [{ id: 'card', kind: 'color', color: '#123456', duration: 0.3 }];
  project.captions = [];
  await writeFile(file, JSON.stringify(project));
  const failed = await call(['render', 'demo/project.json', '--out', 'final.mp4'], cwd, { FFMPEG_PATH: join(cwd, 'missing-encoder.exe') });
  assert.equal(failed.data.ok, false);
  assert.ok(failed.data.jobId);
  const resumed = await call(['resume', 'demo', '--job', failed.data.jobId], cwd);
  assert.equal(resumed.code, 0, JSON.stringify(resumed.data));
  assert.equal(resumed.data.job.status, 'succeeded');
  assert.equal(resumed.data.job.resumedFrom, failed.data.jobId);
  assert.notEqual(resumed.data.job.id, failed.data.jobId);
  assert.equal((await call(['status', 'demo', '--job', failed.data.jobId], cwd)).data.job.status, 'failed');
  await readFile(join(cwd, 'final.mp4'));
});

test('CLI resumes only the failed batch cut after its supplied media is repaired', async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'agent-video-tool-batch-'));
  await call(['init', 'project'], cwd);
  const projectPath = join(cwd, 'project', 'project.json');
  const project = JSON.parse(await readFile(projectPath, 'utf8'));
  project.canvas = { width: 160, height: 240, fps: 10 };
  project.clips = [{ id: 'base', kind: 'color', color: '#123456', duration: 0.3 }];
  project.captions = [];
  await writeFile(projectPath, JSON.stringify(project));
  const image = join(cwd, 'project', 'assets', 'image.png');
  await writeFile(image, 'not valid media');
  await writeFile(join(cwd, 'variants.json'), JSON.stringify([
    { id: 'repair', patch: { clips: [{ id: 'image', kind: 'image', src: 'assets/image.png', duration: 0.3 }] } },
    { id: 'preserve', patch: {} },
  ]));
  const failed = await call(['batch', projectPath, '--variants', join(cwd, 'variants.json'), '--out-dir', join(cwd, 'cuts')], cwd);
  assert.equal(failed.code, 1);
  assert.equal(failed.data.batch.status, 'partial');
  const completed = failed.data.batch.variants[1];
  const original = await readFile(completed.output);
  await exec(process.env.FFMPEG_PATH || 'ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'color=c=yellow:s=64x64', '-frames:v', '1', '-threads', '1', '-y', image], { windowsHide: true });
  const resumed = await call(['resume-batch', join(cwd, 'cuts')], cwd);
  assert.equal(resumed.code, 0, JSON.stringify(resumed.data));
  assert.equal(resumed.data.batch.status, 'succeeded');
  assert.equal(resumed.data.batch.variants[1].jobId, completed.jobId);
  assert.deepEqual(await readFile(completed.output), original);
  assert.ok(resumed.data.batch.variants[0].previousJobIds.includes(failed.data.batch.variants[0].jobId));
  await readFile(join(cwd, 'cuts', 'repair.mp4'));
});
