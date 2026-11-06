import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { promisify } from 'node:util';
import test from 'node:test';
import { checkFrameflowFiles, validateBrief, validateInputs, validateStoryboard, validateTimings } from '../src/frameflow.mjs';

const exec = promisify(execFile);
const brief = () => ({ title: 'Adapted reel', format: 'reel', aspect: '9:16', target_seconds: 6, audience: 'Creators', tone: 'Direct', summary: 'A supplied-media demonstration.' });
const inputs = () => validateInputs({ footage: [{ name: 'recording.mp4', source: 'assets/recording.mp4', duration: 6 }], assets: [{ path: 'assets/still.png', kind: 'image' }, { path: 'assets/insert.mp4', kind: 'clip', duration: 2, size: '160x240' }], music: [{ path: 'assets/music.wav', duration: 6 }], script: null });
const full = () => ({ script: 'The supplied performance.', scenes: [{ visual: { type: 'footage', source: 'recording.mp4', start: 0, end: 6 }, reason: 'Retain the original recording.' }] });
const options = () => ({ inputs: inputs(), brief: brief() });

test('brief normalization selects explicit project FPS and retains independent creative fields', () => {
  const raw = brief();
  assert.equal(validateBrief(raw).fps, 30);
  assert.equal(raw.fps, undefined);
  assert.equal(validateBrief({ ...raw, fps: 24 }).fps, 24);
  for (const change of [{ fps: 29.97 }, { fps: '30' }, { aspect: '4:3' }, { target_seconds: 86401 }, { target_seconds: 0 }, { title: '' }, { mystery: true }, { skills: [{ name: 'Edit', why: '' }] }]) {
    assert.throws(() => validateBrief({ ...raw, ...change }), { code: 'INVALID_FRAMEFLOW_BRIEF' });
  }
});

test('normalizes the actual inventory shape with script:null, clip size and local absolute paths', () => {
  const normalized = validateInputs({ footage: [{ name: 'take.mp4', source: 'a/take.mp4', duration: 6000, folder: 'timing/take' }], assets: [{ path: 'a/clip.mp4', kind: 'clip', duration: 2, size: '1280x720' }], music: [], prompt: '', script: null }, { baseDir: resolve('test-source') });
  assert.equal(normalized.footage[0].source, resolve('test-source/a/take.mp4'));
  assert.equal(normalized.footage[0].folder, resolve('test-source/timing/take'));
  assert.equal(normalized.assets[0].size, '1280x720');
  assert.equal(normalized.script, null);
  assert.deepEqual(normalized.music, []);
});

test('rejects protocol paths, ambiguous source names and malformed inventory fields', () => {
  for (const path of ['https://example.com/a.mp4', 'file:///tmp/a.mp4', 'concat:a.mp4|b.mp4', 'C:relative.mp4', '//server/share/a.mp4']) {
    assert.throws(() => validateInputs({ footage: [{ name: 'a.mp4', source: path, duration: 1 }] }), { code: 'INVALID_FRAMEFLOW_INPUTS' });
  }
  assert.throws(() => validateInputs({ footage: [{ name: 'same.mp4', source: 'one/same.mp4', duration: 1 }, { name: 'SAME.MP4', source: 'two/same.mp4', duration: 1 }] }), { code: 'INVALID_FRAMEFLOW_INPUTS' });
  assert.throws(() => validateInputs({ assets: [{ path: 'one/a.png', kind: 'image' }, { path: 'two/A.PNG', kind: 'image' }] }), { code: 'INVALID_FRAMEFLOW_INPUTS' });
  for (const change of [{ footage: 'no' }, { assets: [{ path: 'clip.mp4', kind: 'clip' }] }, { music: [{ path: 'music.wav', extra: 1 }] }, { extra: true }]) {
    assert.throws(() => validateInputs(change), { code: 'INVALID_FRAMEFLOW_INPUTS' });
  }
});

test('a complete source interval needs no pause evidence and returns explicit delegated requirements', () => {
  const result = validateStoryboard(full(), options());
  assert.equal(result.duration, 6);
  assert.equal(result.timeline[0].source, inputs().footage[0].source);
  assert.equal(result.timeline[0].sourceIn, 0);
  assert.equal(result.timeline[0].sourceOut, 6);
  assert.ok(result.requirements.includes('native-project-export'));
  assert.ok(result.requirements.includes('human-edit-reconciliation'));
});

test('retains current Frameflow beat-cut declarations while making timeline rebuilding explicit', () => {
  const board = { ...full(), music: { path: 'music.wav', cut_to_beat: true } };
  const result = validateStoryboard(board, options());
  assert.equal(result.storyboard.music.cut_to_beat, true);
  assert.ok(result.requirements.includes('beat-timing-rebuild'));
  assert.ok(result.warnings.some(value => /provisional/i.test(value)));
  assert.equal(validateStoryboard({ ...board, music: { ...board.music, cut_to_beat: false } }, options()).storyboard.music.cut_to_beat, false);
  assert.throws(() => validateStoryboard({ ...board, music: { ...board.music, cut_to_beat: 'yes' } }, options()), { code: 'INVALID_FRAMEFLOW_STORYBOARD' });
});

test('preserves supplied B-roll declarations on footage without inventing phrase timing', () => {
  const board = full();
  board.scenes[0].broll = [{ path: 'still.png', duration: 1 }, { path: 'insert.mp4', start: 0.2, duration: 0.5, when: 'show the result' }];
  const result = validateStoryboard(board, options());
  assert.equal(result.storyboard.scenes[0].broll[0].path, inputs().assets[0].path);
  assert.equal(result.storyboard.scenes[0].broll[1].when, 'show the result');
  assert.ok(result.requirements.includes('broll-placement'));
  assert.ok(result.requirements.includes('phrase-anchor-review'));
  assert.ok(result.warnings.some(value => /phrase/i.test(value)));
  for (const broll of [[], [{ path: 'missing.mp4' }], [{ path: 'still.png', start: 0 }], [{ path: 'insert.mp4', duration: 0 }], [{ path: 'insert.mp4', start: 1.8, duration: 0.5 }], [{ path: 'still.png', extra: true }]]) {
    const invalid = full(); invalid.scenes[0].broll = broll;
    assert.throws(() => validateStoryboard(invalid, options()), { code: 'INVALID_FRAMEFLOW_STORYBOARD' });
  }
  assert.throws(() => validateStoryboard({ script: 'Still', scenes: [{ visual: { type: 'asset', path: 'still.png' }, duration: 1, reason: 'A still.', broll: [{ path: 'insert.mp4' }] }] }, options()), { code: 'INVALID_FRAMEFLOW_STORYBOARD' });
});

test('B-roll source windows remain inside the clip after project-frame rounding', () => {
  const supplied = validateInputs({ footage: [{ name: 'recording.mp4', source: 'recording.mp4', duration: 6 }], assets: [{ path: 'tail.mp4', kind: 'clip', duration: 1.01 }] });
  const board = full(); board.scenes[0].broll = [{ path: 'tail.mp4', start: 0.05, duration: 0.96 }];
  assert.throws(() => validateStoryboard(board, { inputs: supplied, brief: brief() }), error => error.code === 'INVALID_FRAMEFLOW_STORYBOARD' && /rounding/i.test(error.message));
});

test('all narration/voice generation is refused even when its value is empty', () => {
  assert.throws(() => validateStoryboard({ ...full(), voice: '' }, options()), { code: 'GENERATION_NOT_ALLOWED' });
  const board = full(); board.scenes[0].narration = '';
  assert.throws(() => validateStoryboard(board, options()), { code: 'GENERATION_NOT_ALLOWED' });
});

test('storyboards reject unknown keys, missing durations, invalid asset windows, and unresolved briefs', () => {
  for (const visual of [{ type: 'image', path: 'still.png' }, { type: 'title', text: 'Title' }, { type: 'asset', path: 'still.png', start: 1 }]) {
    assert.throws(() => validateStoryboard({ script: 'Test', scenes: [{ visual, reason: 'A scene.' }] }, options()), { code: 'INVALID_FRAMEFLOW_STORYBOARD' });
  }
  assert.throws(() => validateStoryboard({ ...full(), extra: true }, options()), { code: 'INVALID_FRAMEFLOW_STORYBOARD' });
  assert.throws(() => validateStoryboard({ script: 'Test', scenes: [{ visual: { type: 'asset', path: 'insert.mp4', start: 1 }, duration: 2, reason: 'Too long.' }] }, options()), { code: 'INVALID_FRAMEFLOW_STORYBOARD' });
  assert.throws(() => validateStoryboard(full(), { ...options(), brief: { ...brief(), open_questions: ['Which subject?'] } }), { code: 'INVALID_FRAMEFLOW_BRIEF' });
});

test('rejects an asset tail that exceeds its source only after Frameflow rounds start and length', () => {
  const supplied = validateInputs({ assets: [{ path: 'clip.mp4', kind: 'clip', duration: 1.01 }] });
  const board = { script: 'Clip', scenes: [{ visual: { type: 'asset', path: 'clip.mp4', start: 0.05 }, reason: 'A selected tail.' }] };
  assert.throws(() => validateStoryboard(board, { inputs: supplied, brief: brief() }), { code: 'INVALID_FRAMEFLOW_STORYBOARD' });
});

test('Frameflow JSON handoffs support long storyboards independently of the reference renderer limit', () => {
  const supplied = validateInputs({ footage: [{ name: 'long.mp4', source: 'long.mp4', duration: 3600 }] });
  const board = { script: 'Existing long recording.', scenes: [{ visual: { type: 'footage', source: 'long.mp4', start: 0, end: 3600 }, reason: 'Keep the supplied material editable.' }] };
  assert.equal(validateStoryboard(board, { inputs: supplied, brief: { ...brief(), target_seconds: 3600 } }).duration, 3600);
});

test('interior source cuts need measured pauses, not words, and preserve one-frame margins after rounding', () => {
  const board = full(); board.scenes[0].visual.end = 2.2;
  assert.throws(() => validateStoryboard(board, options()), { code: 'UNSAFE_FRAMEFLOW_CUT' });
  assert.throws(() => validateStoryboard(board, { ...options(), timings: { 'recording.mp4': { pauses: [], words: [{ text: 'Word', start: 2, end: 2.2 }] } } }), { code: 'UNSAFE_FRAMEFLOW_CUT' });
  const timings = { 'recording.mp4': { pauses: [{ start: 2, end: 2.4 }] } };
  assert.equal(validateStoryboard(board, { ...options(), timings }).duration, 2.2);
  board.scenes[0].visual.end = 2.01;
  assert.throws(() => validateStoryboard(board, { ...options(), timings }), { code: 'UNSAFE_FRAMEFLOW_CUT' });
  board.scenes[0].visual.end = 2.05;
  assert.throws(() => validateStoryboard(board, { ...options(), timings: { 'recording.mp4': { pauses: [{ start: 2, end: 2.09 }] } } }), { code: 'UNSAFE_FRAMEFLOW_CUT' });
});

test('retains fractional source seconds, reports quantization and matches Frameflow ties-to-even', () => {
  const board = full(); board.scenes[0].visual.end = 2.25;
  const result = validateStoryboard(board, { ...options(), brief: { ...brief(), fps: 30 }, timings: { 'recording.mp4': { pauses: [{ start: 2, end: 2.5 }] } } });
  assert.equal(result.storyboard.scenes[0].visual.end, 2.25);
  assert.equal(result.timeline[0].sourceOut, 2.25);
  assert.equal(result.duration, 68 / 30); // 67.5 rounds to the even frame 68.
  assert.ok(result.warnings.some(value => /quantiz/i.test(value)));
  board.scenes[0].visual.end = 2.15;
  const down = validateStoryboard(board, { ...options(), timings: { 'recording.mp4': { pauses: [{ start: 2, end: 2.5 }] } } });
  assert.equal(down.duration, 64 / 30); // 64.5 rounds down to even frame 64.
});

test('validates source-clock pause/word documents before any storyboard exists', () => {
  const supplied = inputs();
  assert.deepEqual(validateTimings({}, supplied), {});
  for (const timings of [[], { wrong: { pauses: [] } }, { 'recording.mp4': { pauses: [{ start: 2, end: 1 }] } }, { 'recording.mp4': { pauses: [{ start: 0, end: 7 }] } }, { 'recording.mp4': { pauses: [{ start: 1, end: 2 }, { start: 1.5, end: 3 }] } }, { 'recording.mp4': { pauses: [], words: [{ text: 'word', start: 1, end: 0 }] } }]) {
    assert.throws(() => validateTimings(timings, supplied), { code: 'INVALID_FRAMEFLOW_TIMINGS' });
  }
});

test('source names matching prototype properties retain owned timing evidence through JSON round trips', () => {
  const supplied = validateInputs({ footage: [{ name: '__proto__', source: 'proto.mp4', duration: 6 }] });
  const raw = JSON.parse('{"__proto__":{"pauses":[{"start":2,"end":3}]}}');
  const normalized = validateTimings(raw, supplied);
  assert.equal(Object.hasOwn(normalized, '__proto__'), true);
  assert.equal(Object.getPrototypeOf(normalized), Object.prototype);
  assert.deepEqual(JSON.parse(JSON.stringify(normalized)), raw);
  const board = { script: 'Supplied clip', scenes: [{ visual: { type: 'footage', source: '__proto__', start: 0, end: 2.5 }, reason: 'A safe cut.' }] };
  assert.equal(validateStoryboard(board, { inputs: supplied, brief: brief(), timings: JSON.parse(JSON.stringify(normalized)) }).duration, 2.5);
});

test('supports supplied stills, clip assets, music and delegated graphics without executing HTML', () => {
  const board = { script: 'An adapted opening.', spoken_captions: true, music: { path: 'music.wav', volume_db: -12 }, scenes: [
    { visual: { type: 'asset', path: 'still.png' }, duration: 1, reason: 'Show the product.', cards: [{ kind: 'product', text: 'Product', price: '$10', duration: 0.5 }] },
    { visual: { type: 'asset', path: 'insert.mp4', start: 0.5 }, duration: 1, reason: 'Show it moving.' },
    { visual: { type: 'title', text: 'Take action' }, duration: 1, reason: 'Close clearly.' },
    { visual: { type: 'composition', path: 'graphics/cta' }, duration: 1, reason: 'An authored visual.' },
  ] };
  const result = validateStoryboard(board, { ...options(), baseDir: resolve('project') });
  assert.equal(result.storyboard.scenes[3].visual.path, resolve('project/graphics/cta'));
  assert.equal(result.duration, 4);
  for (const requirement of ['caption-rendering', 'card-rendering', 'custom-html-composition']) assert.ok(result.requirements.includes(requirement));
  assert.throws(() => validateStoryboard({ ...board, scenes: [{ ...board.scenes[0], cards: [{ kind: 'lower_third', text: 'Name', price: '$10' }] }] }, options()), { code: 'INVALID_FRAMEFLOW_STORYBOARD' });
});

test('checks all real supplied files and advertised durations, plus composition index.html, without writing', async () => {
  const root = await mkdtemp(join(tmpdir(), 'agent-video-frameflow-'));
  const video = join(root, 'recording.mp4');
  const image = join(root, 'still.png');
  const music = join(root, 'music.wav');
  await exec(process.env.FFMPEG_PATH || 'ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'color=c=blue:s=160x240:r=30:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-n', video], { windowsHide: true });
  await exec(process.env.FFMPEG_PATH || 'ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'color=c=red:s=64x64', '-frames:v', '1', '-threads', '1', '-n', image], { windowsHide: true });
  await exec(process.env.FFMPEG_PATH || 'ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-n', music], { windowsHide: true });
  const supplied = validateInputs({ footage: [{ name: 'recording.mp4', source: video, duration: 1 }], assets: [{ path: image, kind: 'image' }], music: [{ path: music, duration: 1 }] });
  assert.equal((await checkFrameflowFiles(supplied)).files.length, 3);
  const withInsert = validateInputs({ ...supplied, assets: [...supplied.assets, { path: video, kind: 'clip', duration: 1 }] });
  const cutaway = { script: 'Supplied footage.', scenes: [{ visual: { type: 'footage', source: 'recording.mp4', start: 0, end: 1 }, reason: 'Demonstration.', broll: [{ path: video, start: 0.2, duration: 0.5 }] }] };
  assert.equal((await checkFrameflowFiles(withInsert, cutaway, { brief: brief() })).checked, true);
  cutaway.scenes[0].broll[0].duration = 1;
  await assert.rejects(checkFrameflowFiles(withInsert, cutaway, { brief: brief() }), { code: 'INVALID_FRAMEFLOW_FILE' });
  const composition = join(root, 'composition'); await mkdir(composition);
  const board = { script: 'Title', scenes: [{ visual: { type: 'composition', path: composition }, duration: 1, reason: 'Existing graphics.' }] };
  await assert.rejects(checkFrameflowFiles(supplied, board, { brief: brief() }), { code: 'INVALID_FRAMEFLOW_FILE' });
  await writeFile(join(composition, 'index.html'), '<script>throw new Error("must never execute")</script>');
  assert.equal((await checkFrameflowFiles(supplied, board, { brief: brief() })).checked, true);
  await assert.rejects(checkFrameflowFiles(supplied, board), { code: 'INVALID_FRAMEFLOW_FILE' });
  await assert.rejects(checkFrameflowFiles({ ...supplied, footage: [{ ...supplied.footage[0], duration: 2 }] }), { code: 'INVALID_FRAMEFLOW_FILE' });
  const slow = join(root, 'one-frame.mp4');
  await exec(process.env.FFMPEG_PATH || 'ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:r=1:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-n', slow], { windowsHide: true });
  await assert.rejects(checkFrameflowFiles({ footage: [{ name: 'one-frame.mp4', source: slow, duration: 2 }] }), { code: 'INVALID_FRAMEFLOW_FILE' });
  const controller = new AbortController(); controller.abort();
  await assert.rejects(checkFrameflowFiles(supplied, undefined, { signal: controller.signal }), { code: 'CANCELLED' });
});
