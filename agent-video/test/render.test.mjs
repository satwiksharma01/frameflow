import test from 'node:test';
import assert from 'node:assert/strict';
import { copyFile, mkdtemp, mkdir, readFile, rm, stat, unlink, utimes, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { checkTools, probeMedia, renderVideo } from '../src/render.mjs';

const exec = promisify(execFile);
const canvas = { width: 160, height: 240, fps: 10 };

async function workspace(t) {
  const root = await mkdtemp(join(tmpdir(), 'agent-video-render-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const workDir = join(root, 'work');
  await mkdir(workDir);
  return { root, workDir };
}

function project(clips, captions = [], audio = []) {
  return { version: 1, title: 'Renderer test', canvas, clips, captions, audio };
}

async function runFfmpeg(args) {
  await exec(process.env.FFMPEG_PATH || 'ffmpeg', ['-hide_banner', '-loglevel', 'error', '-nostdin', ...args], { windowsHide: true });
}

async function rms(file, start = 0, duration) {
  const { stdout } = await exec(process.env.FFMPEG_PATH || 'ffmpeg', ['-v', 'error', '-nostdin', '-ss', String(start), '-i', file, ...(duration === undefined ? [] : ['-t', String(duration)]), '-vn', '-f', 'f32le', '-ac', '1', '-ar', '8000', 'pipe:1'], { encoding: 'buffer', windowsHide: true });
  let energy = 0;
  for (let offset = 0; offset < stdout.length; offset += 4) energy += stdout.readFloatLE(offset) ** 2;
  return Math.sqrt(energy / (stdout.length / 4));
}

async function pixel(file, time, x = 0, y = 0) {
  const { stdout } = await exec(process.env.FFMPEG_PATH || 'ffmpeg', ['-v', 'error', '-nostdin', '-ss', String(time), '-i', file, '-frames:v', '1', '-vf', `crop=2:2:${x}:${y},format=rgb24`, '-f', 'rawvideo', 'pipe:1'], { encoding: 'buffer', windowsHide: true });
  return [...stdout.subarray(0, 3)];
}

test('tools return their versions and a missing executable gives a useful error', async () => {
  const versions = await checkTools();
  assert.match(versions.ffmpeg, /ffmpeg version/);
  assert.match(versions.ffprobe, /ffprobe version/);
  const previous = process.env.FFMPEG_PATH;
  process.env.FFMPEG_PATH = join(tmpdir(), 'agent-video-not-an-executable-42');
  try {
    await assert.rejects(checkTools(), error => error.code === 'TOOL_UNAVAILABLE' && /FFMPEG_PATH/.test(error.message));
  } finally {
    if (previous === undefined) delete process.env.FFMPEG_PATH;
    else process.env.FFMPEG_PATH = previous;
  }
});

test('renders sequential colors with literal timed text and reports a playable video', async t => {
  const { root, workDir } = await workspace(t);
  const text = "50% ready: don't execute %{eif:1+1:d}\nSecond line [x], a;b";
  const p = project([
    { id: 'one', kind: 'color', color: '#13243a', duration: 0.45 },
    { id: 'two', kind: 'color', color: '#df6b3b', duration: 0.45 },
  ], [{ text, start: 0, end: 0.9, position: 'center', fontSize: 12, color: '#ffffff' }]);
  const progress = [];
  const rendered = await renderVideo({ project: p, projectPath: join(root, 'project.json'), root }, { workDir, onProgress: p => progress.push(p) });
  const metadata = await probeMedia(rendered.file);
  const video = metadata.streams.find(stream => stream.codec_type === 'video');
  assert.equal(video.width, 160);
  assert.equal(video.height, 240);
  assert.equal(video.r_frame_rate, '10/1');
  assert.ok(Math.abs(Number(metadata.format.duration) - 0.9) < 0.15);
  assert.equal(rendered.duration, 0.9);
  assert.ok(metadata.streams.some(stream => stream.codec_type === 'audio'));
  assert.ok(progress.some(p => p.stage === 'clips' && p.completed === 2));
  assert.equal(await readFile(join(workDir, 'caption-0.txt'), 'utf8'), text);
  const first = await pixel(rendered.file, 0.1);
  const second = await pixel(rendered.file, 0.6);
  assert.ok(first[2] > first[0], 'the first clip should be navy');
  assert.ok(second[0] > second[2], 'the second clip should be orange');
});

test('preserves source audio, holds an image, and can mute the source', async t => {
  const { root, workDir } = await workspace(t);
  const source = join(root, 'source.mp4');
  await runFfmpeg(['-f', 'lavfi', '-i', 'color=c=blue:s=100x100:r=10:d=1', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', '-y', source]);
  await runFfmpeg(['-f', 'lavfi', '-i', 'color=c=yellow:s=100x100', '-frames:v', '1', '-threads', '1', '-y', join(root, 'still.png')]);
  const p = project([
    { id: 'source', kind: 'video', src: 'source.mp4', in: 0.2, duration: 0.4, volume: 1 },
    { id: 'image', kind: 'image', src: 'still.png', duration: 0.2 },
  ]);
  const rendered = await renderVideo({ project: p, projectPath: join(root, 'project.json'), root }, { workDir });
  assert.ok(await rms(rendered.file) > 0.02, 'the video audio should be present');
  const mutedDir = join(root, 'muted');
  await mkdir(mutedDir);
  p.clips[0].volume = 0;
  const muted = await renderVideo({ project: p, projectPath: join(root, 'project.json'), root }, { workDir: mutedDir });
  assert.ok(await rms(muted.file) < 0.0001, 'muted clips and images should be silent');
});

test('mixes an added audio track into a color-only project', async t => {
  const { root, workDir } = await workspace(t);
  await runFfmpeg(['-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000:duration=1', '-y', join(root, 'music.wav')]);
  const p = project([{ id: 'background', kind: 'color', color: '#000000', duration: 0.5 }], [], [{ src: 'music.wav', start: 0.1, in: 0.2, duration: 0.3, volume: 0.5 }]);
  const rendered = await renderVideo({ project: p, projectPath: join(root, 'project.json'), root }, { workDir });
  assert.ok(await rms(rendered.file) > 0.005);
});

test('rejects source intervals past the media duration before rendering', async t => {
  const { root, workDir } = await workspace(t);
  await runFfmpeg(['-f', 'lavfi', '-i', 'color=c=red:s=100x100:r=10:d=0.3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', join(root, 'short.mp4')]);
  const p = project([{ id: 'short', kind: 'video', src: 'short.mp4', in: 0.2, duration: 0.4, volume: 1 }]);
  await assert.rejects(renderVideo({ project: p, projectPath: join(root, 'project.json'), root }, { workDir }), error => error.code === 'MEDIA_TOO_SHORT');
  p.clips[0].in = 0;
  p.clips[0].duration = 0.2;
  const rendered = await renderVideo({ project: p, projectPath: join(root, 'project.json'), root }, { workDir });
  assert.ok(await rms(rendered.file) < 0.0001, 'a source without audio should receive silence');
});

test('an aborted render stops its child process and rejects as cancelled', async t => {
  const { root, workDir } = await workspace(t);
  const controller = new AbortController();
  const p = project([{ id: 'background', kind: 'color', color: '#000000', duration: 0.3 }]);
  const stages = [];
  await assert.rejects(renderVideo({ project: p, projectPath: join(root, 'project.json'), root }, {
    workDir,
    signal: controller.signal,
    onProgress(progress) {
      stages.push(progress);
      if (progress.stage === 'compose' && progress.completed === 0) controller.abort();
    },
  }), error => error.code === 'CANCELLED');
  assert.ok(!stages.some(p => p.stage === 'compose' && p.completed === 1));
});

test('awaits progress persistence and propagates asynchronous callback failures', async t => {
  const { root, workDir } = await workspace(t);
  const p = project([{ id: 'background', kind: 'color', color: '#000000', duration: 0.2 }]);
  const rejected = new Error('Cannot persist the job progress');
  await assert.rejects(renderVideo({ project: p, projectPath: join(root, 'project.json'), root }, {
    workDir,
    async onProgress() { throw rejected; },
  }), error => error === rejected);
});

test('renders the full 200-caption allowance without exceeding Windows argument limits', async t => {
  const { root, workDir } = await workspace(t);
  const captions = Array.from({ length: 200 }, (_, index) => ({
    text: `Caption ${index}`, start: index / 1000, end: (index + 1) / 1000,
    position: 'center', fontSize: 12, color: '#ffffff',
  }));
  const p = project([{ id: 'background', kind: 'color', color: '#000000', duration: 0.2 }], captions);
  const rendered = await renderVideo({ project: p, projectPath: join(root, 'project.json'), root }, { workDir });
  const metadata = await probeMedia(rendered.file);
  assert.ok(Math.abs(Number(metadata.format.duration) - 0.2) < 0.15);
  assert.equal(await readFile(join(workDir, 'caption-199.txt'), 'utf8'), 'Caption 199');
});

test('rejects a disguised local playlist before following paths outside the project', async t => {
  const { root, workDir } = await workspace(t);
  const projectRoot = join(root, 'project');
  await mkdir(projectRoot);
  await runFfmpeg(['-f', 'lavfi', '-i', 'color=c=red:s=100x100:r=10:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-f', 'mpegts', '-y', join(root, 'outside.ts')]);
  const playlist = join(projectRoot, 'playlist.m3u8');
  await writeFile(playlist, '#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:1.0,\n../outside.ts\n#EXT-X-ENDLIST\n');
  await assert.rejects(probeMedia(playlist), error => /whitelist/i.test(error.message));
  const p = project([{ id: 'outside', kind: 'video', src: 'playlist.m3u8', in: 0, duration: 0.2, volume: 0 }]);
  await assert.rejects(renderVideo({ project: p, projectPath: join(projectRoot, 'project.json'), root: projectRoot }, { workDir }), error => /whitelist/i.test(error.message));
  const disguised = join(projectRoot, 'disguised.mp4');
  await writeFile(disguised, "ffconcat version 1.0\nfile '../outside.ts'\n");
  await assert.rejects(probeMedia(disguised), error => /whitelist/i.test(error.message));
});

test('reads an image as a single file by its signature and rejects video as an image', async t => {
  const { root, workDir } = await workspace(t);
  await runFfmpeg(['-f', 'lavfi', '-i', 'color=c=yellow:s=100x100', '-frames:v', '1', '-threads', '1', '-y', join(root, 'still.png')]);
  await copyFile(join(root, 'still.png'), join(root, 'frame%03d.data'));
  const p = project([{ id: 'image', kind: 'image', src: 'frame%03d.data', duration: 0.2 }]);
  const rendered = await renderVideo({ project: p, projectPath: join(root, 'project.json'), root }, { workDir });
  const color = await pixel(rendered.file, 0.1);
  assert.ok(color[0] > 200 && color[1] > 200 && color[2] < 20);
  await runFfmpeg(['-f', 'lavfi', '-i', 'color=c=red:s=100x100:r=10:d=0.3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', join(root, 'video.mp4')]);
  p.clips[0].src = 'video.mp4';
  await assert.rejects(renderVideo({ project: p, projectPath: join(root, 'project.json'), root }, { workDir }), error => error.code === 'INVALID_MEDIA' && /still image/.test(error.message));
});

test('word-anchored captions resolve their current text and timestamps at render time', async t => {
  const { root, workDir } = await workspace(t);
  const p = project([{ id: 'card', kind: 'color', color: '#123456', duration: 1 }], [
    { fromWord: 'w1', toWord: 'w2', position: 'center', fontSize: 16, color: '#ffffff' },
  ]);
  p.words = [{ id: 'w1', text: 'Keep', start: 0.2, end: 0.4 }, { id: 'w2', text: 'moving.', start: 0.4, end: 0.7 }];
  await renderVideo({ project: p, root }, { workDir });
  assert.equal(await readFile(join(workDir, 'caption-0.txt'), 'utf8'), 'Keep moving.');
  assert.match(await readFile(join(workDir, 'compose-filter.txt'), 'utf8'), /gte\(t,0\.2\).*lt\(t,0\.7\)/);
});

test('batch-local reuse skips unchanged segments while composing new captions', async t => {
  const { root, workDir } = await workspace(t);
  const clipCache = new Map();
  const p = project([{ id: 'card', kind: 'color', color: '#123456', duration: 0.4 }], [{ text: 'First', start: 0, end: 0.4, fontSize: 16, color: '#ffffff', position: 'center' }]);
  const first = await renderVideo({ project: p, root }, { workDir, clipCache });
  assert.deepEqual(first.cache, { hits: 0, misses: 1 });
  const secondDir = join(root, 'second');
  await mkdir(secondDir);
  p.clips[0].id = 'renamed';
  p.captions[0].text = 'Second';
  const second = await renderVideo({ project: p, root }, { workDir: secondDir, clipCache });
  assert.deepEqual(second.cache, { hits: 1, misses: 0 });
  assert.equal(await readFile(join(secondDir, 'caption-0.txt'), 'utf8'), 'Second');
  assert.notDeepEqual(await readFile(first.file), await readFile(second.file));
  const changedDir = join(root, 'changed');
  await mkdir(changedDir);
  p.clips[0].color = '#abc123';
  const changed = await renderVideo({ project: p, root }, { workDir: changedDir, clipCache });
  assert.deepEqual(changed.cache, { hits: 0, misses: 1 });
});

test('image content hashes invalidate reuse even when file size and timestamps are unchanged', async t => {
  const { root, workDir } = await workspace(t);
  const file = join(root, 'image.bmp');
  await runFfmpeg(['-f', 'lavfi', '-i', 'color=c=red:s=100x100', '-frames:v', '1', '-threads', '1', '-y', file]);
  const original = await stat(file);
  const clipCache = new Map();
  const p = project([{ id: 'image', kind: 'image', src: 'image.bmp', duration: 0.3 }]);
  await renderVideo({ project: p, root }, { workDir, clipCache });
  const hitDir = join(root, 'hit'); await mkdir(hitDir);
  assert.deepEqual((await renderVideo({ project: p, root }, { workDir: hitDir, clipCache })).cache, { hits: 1, misses: 0 });
  await runFfmpeg(['-f', 'lavfi', '-i', 'color=c=blue:s=100x100', '-frames:v', '1', '-threads', '1', '-y', file]);
  assert.equal((await stat(file)).size, original.size);
  await utimes(file, original.atime, original.mtime);
  const newDir = join(root, 'new'); await mkdir(newDir);
  const changed = await renderVideo({ project: p, root }, { workDir: newDir, clipCache });
  assert.deepEqual(changed.cache, { hits: 0, misses: 1 });
  const color = await pixel(changed.file, 0.1);
  assert.ok(color[2] > color[0], 'the replacement source must appear');
});

test('missing or corrupted reused segments are encoded again', async t => {
  const { root, workDir } = await workspace(t);
  const clipCache = new Map();
  const p = project([{ id: 'card', kind: 'color', color: '#123456', duration: 0.2 }]);
  await renderVideo({ project: p, root }, { workDir, clipCache });
  assert.equal(clipCache.size, 1);
  await writeFile([...clipCache.values()][0].file, 'corrupted');
  const recovered = join(root, 'recovered'); await mkdir(recovered);
  assert.deepEqual((await renderVideo({ project: p, root }, { workDir: recovered, clipCache })).cache, { hits: 0, misses: 1 });
  await unlink([...clipCache.values()][0].file);
  const missing = join(root, 'missing'); await mkdir(missing);
  assert.deepEqual((await renderVideo({ project: p, root }, { workDir: missing, clipCache })).cache, { hits: 0, misses: 1 });
});

test('video segment reuse preserves audio and invalidates changed volume or source offset', async t => {
  const { root, workDir } = await workspace(t);
  await runFfmpeg(['-f', 'lavfi', '-i', 'color=c=blue:s=100x100:r=10:d=1', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', '-y', join(root, 'source.mp4')]);
  const clipCache = new Map();
  const p = project([{ id: 'footage', kind: 'video', src: 'source.mp4', in: 0, duration: 0.3, volume: 1 }]);
  await renderVideo({ project: p, root }, { workDir, clipCache });
  const hitDir = join(root, 'video-hit'); await mkdir(hitDir);
  const hit = await renderVideo({ project: p, root }, { workDir: hitDir, clipCache });
  assert.deepEqual(hit.cache, { hits: 1, misses: 0 });
  assert.ok(await rms(hit.file) > 0.02);
  p.clips[0].volume = 0;
  const muteDir = join(root, 'video-mute'); await mkdir(muteDir);
  const muted = await renderVideo({ project: p, root }, { workDir: muteDir, clipCache });
  assert.deepEqual(muted.cache, { hits: 0, misses: 1 });
  assert.ok(await rms(muted.file) < 0.0001);
  p.clips[0].in = 0.2;
  const offsetDir = join(root, 'video-offset'); await mkdir(offsetDir);
  assert.deepEqual((await renderVideo({ project: p, root }, { workDir: offsetDir, clipCache })).cache, { hits: 0, misses: 1 });
});

test('image overlays obey absolute timing, rectangle placement, and opacity', async t => {
  const { root, workDir } = await workspace(t);
  await runFfmpeg(['-f', 'lavfi', '-i', 'color=c=red:s=100x100', '-frames:v', '1', '-threads', '1', '-y', join(root, 'overlay.png')]);
  const p = project([{ id: 'background', kind: 'color', color: '#0000ff', duration: 1.2 }]);
  p.overlays = [{ id: 'picture', kind: 'image', src: 'overlay.png', start: 0.4, duration: 0.5, rect: { x: 20, y: 30, width: 60, height: 80 }, opacity: 0.5 }];
  const rendered = await renderVideo({ project: p, root }, { workDir });
  const before = await pixel(rendered.file, 0.1, 40, 60);
  const inside = await pixel(rendered.file, 0.5, 40, 60);
  const outside = await pixel(rendered.file, 0.5, 2, 2);
  const after = await pixel(rendered.file, 1.0, 40, 60);
  assert.ok(before[2] > 220 && before[0] < 20);
  assert.ok(inside[0] > 90 && inside[0] < 170 && inside[2] > 90 && inside[2] < 170, `half-opacity red on blue: ${inside}`);
  assert.ok(outside[2] > 220 && outside[0] < 20);
  assert.ok(after[2] > 220 && after[0] < 20);
});

test('video overlays use the selected source interval and never mix their own audio', async t => {
  const { root, workDir } = await workspace(t);
  await runFfmpeg(['-f', 'lavfi', '-i', "color=c=red:s=100x100:r=10:d=0.6,drawbox=color=blue:t=fill:enable='gte(t,0.3)'", '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=0.6', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', '-y', join(root, 'overlay.mp4')]);
  const p = project([{ id: 'background', kind: 'color', color: '#ffffff', duration: 0.6 }]);
  p.overlays = [{ id: 'picture', kind: 'video', src: 'overlay.mp4', in: 0.3, start: 0.2, duration: 0.2, rect: { x: 20, y: 30, width: 60, height: 80 }, opacity: 1 }];
  const rendered = await renderVideo({ project: p, root }, { workDir });
  const shown = await pixel(rendered.file, 0.3, 40, 60);
  assert.ok(shown[2] > 200 && shown[0] < 20, `trim should choose blue, not the earlier red frames: ${shown}`);
  const before = await pixel(rendered.file, 0.1, 40, 60);
  assert.ok(before.every(channel => channel > 220));
  assert.ok(await rms(rendered.file) < 0.0001);
  p.overlays[0].in = 0.5;
  await assert.rejects(renderVideo({ project: p, root }, { workDir }), { code: 'MEDIA_TOO_SHORT' });
});

test('clip grading and fades change pixels and invalidate segment reuse', async t => {
  const { root, workDir } = await workspace(t);
  const p = project([{ id: 'card', kind: 'color', color: '#803030', duration: 1 }]);
  const clipCache = new Map();
  const baseline = await renderVideo({ project: p, root }, { workDir, clipCache });
  const base = await pixel(baseline.file, 0.4);
  assert.ok(base[0] > base[1] + 50);
  p.clips[0].effects = { saturation: 0, brightness: 0.3, contrast: 1.1, fadeIn: 0.2, fadeOut: 0.3 };
  const changedDir = join(root, 'graded'); await mkdir(changedDir);
  const graded = await renderVideo({ project: p, root }, { workDir: changedDir, clipCache });
  assert.deepEqual(graded.cache, { hits: 0, misses: 1 });
  const beginning = await pixel(graded.file, 0);
  const middle = await pixel(graded.file, 0.4);
  const ending = await pixel(graded.file, 0.9);
  assert.ok(beginning.every(channel => channel < 15));
  assert.ok(Math.max(...middle) - Math.min(...middle) < 8, `saturation zero should produce gray: ${middle}`);
  assert.ok(middle[0] > 130, `brightness must lighten the image: ${middle}`);
  assert.ok(ending[0] < middle[0] * 0.6, `fade-out must darken the ending: ${ending}`);
});

test('constant centered zoom enlarges image detail', async t => {
  const { root, workDir } = await workspace(t);
  await runFfmpeg(['-f', 'lavfi', '-i', 'color=c=black:s=100x100,drawbox=x=40:y=40:w=20:h=20:color=red:t=fill', '-frames:v', '1', '-threads', '1', '-y', join(root, 'detail.png')]);
  const p = project([{ id: 'image', kind: 'image', src: 'detail.png', duration: 0.3 }]);
  const baseline = await renderVideo({ project: p, root }, { workDir });
  const unzoomed = await pixel(baseline.file, 0.1, 40, 120);
  p.clips[0].effects = { zoom: 2 };
  const zoomDir = join(root, 'zoom'); await mkdir(zoomDir);
  const zoomed = await renderVideo({ project: p, root }, { workDir: zoomDir });
  const enlarged = await pixel(zoomed.file, 0.1, 40, 120);
  assert.ok(unzoomed[0] < 20);
  assert.ok(enlarged[0] > 200 && enlarged[1] < 20);
});

test('audio fades act inside the trimmed track before timeline placement', async t => {
  const { root, workDir } = await workspace(t);
  await runFfmpeg(['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1.5', '-y', join(root, 'tone.wav')]);
  const p = project([{ id: 'background', kind: 'color', color: '#000000', duration: 1.4 }], [], [{ src: 'tone.wav', start: 0.2, in: 0.3, duration: 1, volume: 1, fadeIn: 0.3, fadeOut: 0.3 }]);
  const rendered = await renderVideo({ project: p, root }, { workDir });
  const early = await rms(rendered.file, 0.2, 0.08);
  const middle = await rms(rendered.file, 0.65, 0.1);
  const late = await rms(rendered.file, 1.12, 0.08);
  assert.ok(middle > 0.05);
  assert.ok(early < middle * 0.3, `fade-in should be quieter: ${early} vs ${middle}`);
  assert.ok(late < middle * 0.3, `fade-out should be quieter: ${late} vs ${middle}`);
  assert.ok(await rms(rendered.file, 0, 0.1) < 0.0001);
});

test('standalone renders persist verified relative segment metadata before reporting progress', async t => {
  const { root, workDir } = await workspace(t);
  const p = project([{ id: 'card', kind: 'color', color: '#123456', duration: 0.2 }]);
  await renderVideo({ project: p, root }, {
    workDir,
    async onProgress(progress) {
      if (progress.stage !== 'clips') return;
      const metadata = JSON.parse(await readFile(join(workDir, 'segments.json'), 'utf8'));
      assert.equal(metadata.version, 1);
      assert.equal(metadata.segments.length, 1);
      const entry = metadata.segments[0];
      assert.equal(entry.file, 'clip-0.mp4');
      assert.match(entry.key, /^[0-9a-f]{64}$/);
      assert.match(entry.sha256, /^[0-9a-f]{64}$/);
      assert.equal(entry.bytes, (await stat(join(workDir, entry.file))).size);
    },
  });
});

test('all 32 overlays compose over a reused base segment alongside additional audio', async t => {
  const { root, workDir } = await workspace(t);
  await runFfmpeg(['-f', 'lavfi', '-i', 'color=c=lime:s=100x100', '-frames:v', '1', '-threads', '1', '-y', join(root, 'picture.png')]);
  await runFfmpeg(['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=0.3', '-y', join(root, 'tone.wav')]);
  const p = project([{ id: 'background', kind: 'color', color: '#0000ff', duration: 0.3 }]);
  const clipCache = new Map();
  await renderVideo({ project: p, root }, { workDir, clipCache });
  p.overlays = Array.from({ length: 32 }, (_, index) => ({ id: `layer${index}`, kind: 'image', src: 'picture.png', start: 0, duration: 0.3, rect: { x: 10, y: 20, width: 30, height: 40 }, opacity: 1 }));
  p.audio = [{ src: 'tone.wav', start: 0, in: 0, duration: 0.3, volume: 0.5 }];
  const nextDir = join(root, 'composed'); await mkdir(nextDir);
  const rendered = await renderVideo({ project: p, root }, { workDir: nextDir, clipCache });
  assert.deepEqual(rendered.cache, { hits: 1, misses: 0 });
  const inside = await pixel(rendered.file, 0.1, 20, 30);
  assert.ok(inside[1] > 220 && inside[0] < 20 && inside[2] < 20);
  assert.ok(await rms(rendered.file) > 0.02);
});

test('editing word timing moves picture cuts and B-roll while retaining segment reuse', async t => {
  const { root, workDir } = await workspace(t);
  await runFfmpeg(['-f', 'lavfi', '-i', 'color=c=lime:s=100x100', '-frames:v', '1', '-threads', '1', '-y', join(root, 'picture.png')]);
  const p = project([
    { id: 'blue', kind: 'color', color: '#0000ff', untilWord: 'w1' },
    { id: 'red', kind: 'color', color: '#ff0000', untilWord: 'w2' },
  ], [{ fromWord: 'w1', toWord: 'w2', position: 'bottom', fontSize: 12, color: '#ffffff' }]);
  p.words = [{ id: 'w1', text: 'Cut', start: 0.1, end: 0.4 }, { id: 'w2', text: 'now', start: 0.6, end: 0.8 }];
  p.overlays = [{ id: 'picture', kind: 'image', src: 'picture.png', fromWord: 'w2', toWord: 'w2', rect: { x: 20, y: 30, width: 60, height: 80 } }];
  const clipCache = new Map();
  const first = await renderVideo({ project: p, root }, { workDir, clipCache });
  const originalCut = await pixel(first.file, 0.5);
  const originalOverlay = await pixel(first.file, 0.7, 40, 60);
  assert.ok(originalCut[0] > 220 && originalCut[2] < 20);
  assert.ok(originalOverlay[1] > 220 && originalOverlay[0] < 20, `original anchored overlay: ${originalOverlay}`);
  p.words = [{ id: 'w1', text: 'Switch', start: 0.1, end: 0.6 }, { id: 'w2', text: 'later', start: 0.8, end: 1 }];
  const nextDir = join(root, 'retimed'); await mkdir(nextDir);
  const next = await renderVideo({ project: p, root }, { workDir: nextDir, clipCache });
  assert.deepEqual(next.cache, { hits: 1, misses: 1 });
  const movedCut = await pixel(next.file, 0.5);
  const beforeOverlay = await pixel(next.file, 0.7, 40, 60);
  const movedOverlay = await pixel(next.file, 0.9, 40, 60);
  assert.ok(movedCut[2] > 220 && movedCut[0] < 20);
  assert.ok(beforeOverlay[0] > 220 && beforeOverlay[1] < 20);
  assert.ok(movedOverlay[1] > 220 && movedOverlay[0] < 20, `retimed anchored overlay: ${movedOverlay}`);
  assert.equal(await readFile(join(nextDir, 'caption-0.txt'), 'utf8'), 'Switch later');
  assert.equal(p.clips[0].duration, undefined);
  assert.equal(p.overlays[0].start, undefined);
});

test('segment metadata uses unique exclusive temporary files without touching a fixed preexisting path', async t => {
  const { root, workDir } = await workspace(t);
  const fixed = join(workDir, 'segments.json.tmp');
  await writeFile(fixed, 'leave this file alone');
  const p = project([{ id: 'background', kind: 'color', color: '#123456', duration: 0.2 }]);
  await renderVideo({ project: p, root }, { workDir });
  assert.equal(await readFile(fixed, 'utf8'), 'leave this file alone');
  assert.equal(JSON.parse(await readFile(join(workDir, 'segments.json'), 'utf8')).version, 1);
});

test('sub-frame source offsets retain the covering frame of low-frame-rate footage', async t => {
  const { root, workDir } = await workspace(t);
  await runFfmpeg(['-f', 'lavfi', '-i', 'color=c=red:s=100x100:r=1:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', join(root, 'one-frame.mp4')]);
  const p = project([{ id: 'slow', kind: 'video', src: 'one-frame.mp4', in: 0.2, duration: 0.5, volume: 1 }]);
  const rendered = await renderVideo({ project: p, root }, { workDir });
  const metadata = await probeMedia(rendered.file);
  assert.ok(Math.abs(Number(metadata.format.duration) - 0.5) < 0.05);
  const frame = await pixel(rendered.file, 0.3);
  assert.ok(frame[0] > 220 && frame[1] < 20);
  const overlayDir = join(root, 'overlay'); await mkdir(overlayDir);
  const overlayProject = project([{ id: 'background', kind: 'color', color: '#0000ff', duration: 0.8 }]);
  overlayProject.overlays = [{ id: 'slow', kind: 'video', src: 'one-frame.mp4', in: 0.2, start: 0.1, duration: 0.5, rect: { x: 20, y: 30, width: 60, height: 80 } }];
  const overlay = await renderVideo({ project: overlayProject, root }, { workDir: overlayDir });
  const overlaid = await pixel(overlay.file, 0.4, 40, 60);
  assert.ok(overlaid[0] > 220 && overlaid[2] < 20);
  overlayProject.overlays[0].in = 0.6;
  await assert.rejects(renderVideo({ project: overlayProject, root }, { workDir: overlayDir }), { code: 'MEDIA_TOO_SHORT' });
});

test('variable-frame-rate trimming retains a held frame and its later transition', async t => {
  const { root, workDir } = await workspace(t);
  await runFfmpeg(['-f', 'lavfi', '-i', "color=c=red:s=100x100:r=10:d=1,drawbox=color=blue:t=fill:enable='gte(t,0.8)',select='eq(n,0)+eq(n,8)'", '-fps_mode', 'vfr', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', join(root, 'variable.mp4')]);
  const p = project([{ id: 'vfr', kind: 'video', src: 'variable.mp4', in: 0.2, duration: 0.7, volume: 1 }]);
  const rendered = await renderVideo({ project: p, root }, { workDir });
  const held = await pixel(rendered.file, 0.4);
  const changed = await pixel(rendered.file, 0.6);
  assert.ok(held[0] > 220 && held[2] < 20, `the earlier held frame must remain visible: ${held}`);
  assert.ok(changed[2] > 220 && changed[0] < 20, `the transition must appear at the source timestamp: ${changed}`);
  const overlayDir = join(root, 'overlay'); await mkdir(overlayDir);
  const overlayProject = project([{ id: 'background', kind: 'color', color: '#ffffff', duration: 1 }]);
  overlayProject.overlays = [{ id: 'vfr', kind: 'video', src: 'variable.mp4', in: 0.2, start: 0.1, duration: 0.7, rect: { x: 20, y: 30, width: 60, height: 80 } }];
  const overlay = await renderVideo({ project: overlayProject, root }, { workDir: overlayDir });
  const first = await pixel(overlay.file, 0.3, 40, 60);
  const second = await pixel(overlay.file, 0.7, 40, 60);
  assert.ok(first[0] > 220 && first[2] < 20);
  assert.ok(second[2] > 220 && second[0] < 20);
});

test('preserving video preroll never leaks audio before the selected source offset', async t => {
  const { root, workDir } = await workspace(t);
  await runFfmpeg(['-f', 'lavfi', '-i', 'color=c=red:s=100x100:r=1:d=1', '-f', 'lavfi', '-i', "sine=frequency=440:sample_rate=48000:duration=1,volume=volume=0:enable='gte(t,0.2)'", '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', '-y', join(root, 'audio-preroll.mp4')]);
  const p = project([{ id: 'trimmed', kind: 'video', src: 'audio-preroll.mp4', in: 0.4, duration: 0.3, volume: 1 }]);
  const silent = await renderVideo({ project: p, root }, { workDir });
  assert.ok(await rms(silent.file) < 0.0001, 'tone preceding the selected interval must be discarded');
  p.clips[0].in = 0.1;
  p.clips[0].duration = 0.5;
  const secondDir = join(root, 'later'); await mkdir(secondDir);
  const partial = await renderVideo({ project: p, root }, { workDir: secondDir });
  assert.ok(await rms(partial.file, 0, 0.05) > 0.05, 'the selected tone should start immediately');
  assert.ok(await rms(partial.file, 0.2, 0.1) < 0.0001, 'the selected source offset should shorten the audible tone');
});
