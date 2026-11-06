import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, mkdir, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';
import test from 'node:test';
import { inspectMedia, reconstructMedia } from '../src/media.mjs';
import { loadProject } from '../src/project.mjs';

const exec = promisify(execFile);
async function workspace(t) {
  const root = await mkdtemp(join(tmpdir(), 'agent-video-media-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const workDir = join(root, 'inspection');
  await mkdir(workDir);
  return { root, workDir };
}
async function ffmpeg(args) {
  await exec(process.env.FFMPEG_PATH || 'ffmpeg', ['-v', 'error', '-nostdin', ...args], { windowsHide: true });
}
async function fixture(root) {
  const file = join(root, 'two-shots.mp4');
  await ffmpeg(['-f', 'lavfi', '-i', 'color=c=black:s=160x120:r=10:d=0.8', '-f', 'lavfi', '-i', 'color=c=white:s=160x120:r=10:d=0.8', '-f', 'lavfi', '-i', 'sine=frequency=500:sample_rate=48000:duration=1.6', '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[v]', '-map', '[v]', '-map', '2:a', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', '-n', file]);
  return file;
}

test('reference inspection can prioritize the opening and retains the measured source rate', async t => {
  const { root, workDir } = await workspace(t);
  const report = await inspectMedia(await fixture(root), { workDir, focusOpening: true });
  assert.equal(report.frameRequestedTimes[0], 0);
  assert.ok(report.frameRequestedTimes.includes(0.5));
  assert.ok(report.frameRequestedTimes.includes(1));
  assert.ok(report.frames.length <= 12);
  assert.equal(report.sourceFrameRate, '10/1');
});

test('opening-focused sampling still covers the end of a longer reference', async t => {
  const { root, workDir } = await workspace(t);
  const file = join(root, 'longer-reference.mp4');
  await ffmpeg(['-f', 'lavfi', '-i', 'color=c=blue:s=64x64:r=1:d=30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-n', file]);
  const report = await inspectMedia(file, { workDir, focusOpening: true });
  assert.equal(report.frameTimes[0], 0);
  assert.ok(report.frameTimes.at(-1) > 27);
  assert.ok(report.frames.length <= 12);
});

test('inspection measures real metadata, a cut, frames, contact sheet and a content digest', async t => {
  const { root, workDir } = await workspace(t);
  const file = await fixture(root);
  const report = await inspectMedia(file, { workDir });
  assert.equal(report.source, file);
  assert.equal(report.width, 160);
  assert.equal(report.height, 120);
  assert.equal(report.fps, 10);
  assert.equal(report.hasVideo, true);
  assert.equal(report.hasAudio, true);
  assert.ok(Math.abs(report.duration - 1.6) < 0.03);
  assert.match(report.sha256, /^[a-f0-9]{64}$/);
  assert.ok(report.scenes.some(cut => Math.abs(cut - 0.8) < 0.11));
  assert.ok(report.frames.length >= 2 && report.frames.length <= 12);
  for (const frame of [...report.frames, report.contactSheet]) {
    assert.ok(frame.startsWith(workDir));
    assert.ok((await stat(frame)).size > 0);
  }
  assert.equal(report.frameTimes.length, report.frames.length);
  await assert.rejects(inspectMedia(file, { workDir }), { code: 'OUTPUT_EXISTS' });
});

test('audio-only inspection needs no image and reconstruction requires video', async t => {
  const { root, workDir } = await workspace(t);
  const file = join(root, 'audio.wav');
  await ffmpeg(['-f', 'lavfi', '-i', 'sine=frequency=800:duration=0.4', '-n', file]);
  const report = await inspectMedia(file, { workDir });
  assert.equal(report.hasAudio, true);
  assert.equal(report.hasVideo, false);
  assert.deepEqual(report.frames, []);
  assert.deepEqual(report.scenes, []);
  assert.equal(report.contactSheet, null);
  await assert.rejects(reconstructMedia(file, join(root, 'reconstructed')), { code: 'INVALID_MEDIA' });
});

test('reconstruction makes an editable local project and preserves source offsets/audio', async t => {
  const { root } = await workspace(t);
  const source = await fixture(root);
  const destination = join(root, 'reconstructed');
  const result = await reconstructMedia(source, destination);
  const loaded = await loadProject(result.project);
  assert.ok(loaded.project.clips.length >= 2);
  assert.equal(loaded.project.clips[0].in, 0);
  assert.ok(loaded.project.clips[1].in > 0);
  assert.ok(loaded.project.clips.every(clip => clip.kind === 'video' && clip.volume === 1));
  const copy = join(destination, loaded.project.clips[0].src);
  assert.deepEqual(await readFile(copy), await readFile(source));
  assert.ok((await readFile(result.report, 'utf8')).includes('scenes'));
  await assert.rejects(reconstructMedia(source, destination), { code: 'OUTPUT_EXISTS' });
});

test('invalid settings, playlists, stills without duration and cancellation fail clearly', async t => {
  const { root, workDir } = await workspace(t);
  const file = await fixture(root);
  await assert.rejects(inspectMedia(file, { workDir, sceneThreshold: 2 }), { code: 'INVALID_ARGUMENT' });
  await writeFile(join(root, 'playlist.mp4'), '#EXTM3U\nfile:///elsewhere.ts\n');
  await assert.rejects(inspectMedia(join(root, 'playlist.mp4'), { workDir }));
  await ffmpeg(['-f', 'lavfi', '-i', 'color=c=black:s=64x64', '-frames:v', '1', '-threads', '1', '-n', join(root, 'still.png')]);
  await assert.rejects(inspectMedia(join(root, 'still.png'), { workDir }), { code: 'INVALID_MEDIA' });
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(inspectMedia(file, { workDir, signal: controller.signal }), { code: 'CANCELLED' });
});

test('continuous shots receive representative samples over time and long media is rejected', async t => {
  const { root, workDir } = await workspace(t);
  const file = join(root, 'continuous.mp4');
  await ffmpeg(['-f', 'lavfi', '-i', 'color=c=blue:s=64x64:r=1:d=10', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-n', file]);
  const report = await inspectMedia(file, { workDir });
  assert.deepEqual(report.scenes, []);
  assert.equal(report.frames.length, 5);
  assert.ok(report.frameTimes[0] < 2 && report.frameTimes.at(-1) > 8);
  const long = join(root, 'long.mp4');
  await ffmpeg(['-f', 'lavfi', '-i', 'color=c=black:s=64x64:r=1:d=601', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-n', long]);
  const empty = join(root, 'empty');
  await mkdir(empty);
  await assert.rejects(inspectMedia(long, { workDir: empty }), { code: 'INVALID_MEDIA' });
});

test('single-frame low-frame-rate videos still produce a representative PNG and contact sheet', async t => {
  const { root, workDir } = await workspace(t);
  const file = join(root, 'one-frame.mp4');
  await ffmpeg(['-f', 'lavfi', '-i', 'color=c=red:s=64x64:r=1:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-n', file]);
  const report = await inspectMedia(file, { workDir });
  assert.equal(report.frames.length, 1);
  assert.equal(report.frameTimes[0], 0);
  assert.equal(report.frameRequestedTimes[0], 0.5);
  assert.ok((await stat(report.frames[0])).size > 0);
  assert.ok((await stat(report.contactSheet)).size > 0);
  const result = await reconstructMedia(file, join(root, 'reconstructed'));
  assert.equal((await loadProject(result.project)).project.clips[0].duration, 1);
});
