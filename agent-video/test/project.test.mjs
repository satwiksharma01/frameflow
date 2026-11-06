import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, symlink, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { loadProject, ProjectError, resolveCaptions, resolveClips, resolveOverlays, validateAssets, validateProject } from '../src/project.mjs';

function sample() {
  return {
    version: 1,
    title: 'A small project',
    canvas: { width: 720, height: 1280, fps: 30 },
    clips: [{ id: 'intro', kind: 'color', color: '#142036', duration: 2 }],
  };
}

function invalid(value, path) {
  assert.throws(() => validateProject(value), (error) => {
    assert.ok(error instanceof ProjectError);
    assert.equal(error.code, 'INVALID_PROJECT');
    if (path) assert.ok(error.message.includes(path), error.message);
    return true;
  });
}

test('normalizes optional fields without mutating the supplied project', () => {
  const original = sample();
  original.clips = [{ id: 'shot', kind: 'video', src: 'assets/shot.mp4', duration: 2 }];
  original.captions = [{ text: "Literal: '%{pts}'\nSecond line", start: 0, end: 2 }];
  original.audio = [{ src: 'assets/music.wav', start: 0, duration: 2 }];
  const project = validateProject(original);
  assert.deepEqual(project.clips[0], { ...original.clips[0], in: 0, volume: 1 });
  assert.deepEqual(project.captions[0], {
    ...original.captions[0], position: 'bottom', fontSize: 48, color: '#ffffff',
  });
  assert.deepEqual(project.audio[0], { ...original.audio[0], in: 0, volume: 1 });
  assert.equal(original.clips[0].in, undefined);
  assert.deepEqual(validateProject(sample()).captions, []);
  assert.deepEqual(validateProject(sample()).audio, []);
});

test('requires version, title, valid canvas, and clips', () => {
  invalid(null);
  invalid([]);
  for (const change of [
    { version: 2 }, { title: '' }, { title: ' '.repeat(4) }, { title: 'x'.repeat(201) },
    { canvas: { width: 721, height: 1280, fps: 30 } },
    { canvas: { width: 720, height: 0, fps: 30 } },
    { canvas: { width: 720, height: 1280, fps: 61 } },
    { clips: [] }, { clips: new Array(101).fill(sample().clips[0]) },
  ]) invalid({ ...sample(), ...change });
  const missing = sample();
  delete missing.title;
  invalid(missing, 'title');
});

test('rejects unknown keys at every object boundary', () => {
  invalid({ ...sample(), surprise: 1 }, 'surprise');
  invalid({ ...sample(), canvas: { ...sample().canvas, ratio: '9:16' } }, 'ratio');
  invalid({ ...sample(), clips: [{ ...sample().clips[0], colour: '#ffffff' }] }, 'colour');
  invalid({ ...sample(), captions: [{ text: 'Hello', start: 0, end: 1, fontsize: 20 }] }, 'fontsize');
  invalid({ ...sample(), audio: [{ src: 'sound.wav', start: 0, duration: 1, gain: 2 }] }, 'gain');
  invalid(JSON.parse('{"version":1,"__proto__":{"polluted":true}}'), '__proto__');
});

test('enforces clip kinds, kind-specific fields, and unique valid IDs', () => {
  for (const clip of [
    { id: 'bad id', kind: 'color', color: '#ffffff', duration: 1 },
    { id: 'first', kind: 'color', color: 'white', duration: 1 },
    { id: 'first', kind: 'color', color: '#ffffff', duration: 1, src: 'x' },
    { id: 'first', kind: 'image', src: 'x.png', duration: 1, volume: 1 },
    { id: 'first', kind: 'image', duration: 1 },
    { id: 'first', kind: 'other', duration: 1 },
    { id: 'first', kind: 'video', src: 'x.mp4', duration: 1, in: -1 },
    { id: 'first', kind: 'video', src: 'x.mp4', duration: 1, volume: 4.1 },
  ]) invalid({ ...sample(), clips: [clip] });
  invalid({ ...sample(), clips: [sample().clips[0], sample().clips[0]] }, 'id');
  const image = { id: 'picture', kind: 'image', src: 'assets/photo.png', duration: 1 };
  assert.deepEqual(validateProject({ ...sample(), clips: [image] }).clips, [image]);
});

test('rejects invalid numbers and timelines longer than ten minutes', () => {
  for (const duration of [0, -1, 0.001, NaN, Infinity, '2', 601]) {
    invalid({ ...sample(), clips: [{ ...sample().clips[0], duration }] }, 'duration');
  }
  invalid({ ...sample(), clips: [
    { ...sample().clips[0], duration: 400 },
    { ...sample().clips[0], id: 'second', duration: 300 },
  ] }, 'duration');
});

test('defaults apply to missing values, not explicit nulls', () => {
  invalid({ ...sample(), captions: null }, 'captions');
  invalid({ ...sample(), audio: null }, 'audio');
  invalid({ ...sample(), clips: [{ id: 'clip', kind: 'video', src: 'x.mp4', duration: 1, volume: null }] }, 'volume');
  invalid({ ...sample(), captions: [{ text: 'A line', start: 0, end: 1, position: null }] }, 'position');
});

test('caption and audio timing stay inside the final timeline', () => {
  for (const caption of [
    { text: '', start: 0, end: 1 }, { text: 'a', start: -1, end: 1 },
    { text: 'a', start: 1, end: 1 }, { text: 'a', start: 1, end: 3 },
    { text: 'a', start: 0, end: 1, position: 'left' },
    { text: 'a', start: 0, end: 1, fontSize: 1 },
    { text: 'a', start: 0, end: 1, color: 'red' },
  ]) invalid({ ...sample(), captions: [caption] });
  for (const track of [
    { src: 'x.wav', start: 0, duration: 0 },
    { src: 'x.wav', start: 1, duration: 2 },
    { src: 'x.wav', start: 0, duration: 1, in: -1 },
    { src: 'x.wav', start: 0, duration: 1, volume: -1 },
  ]) invalid({ ...sample(), audio: [track] });
  invalid({ ...sample(), captions: new Array(201).fill({ text: 'a', start: 0, end: 1 }) });
  invalid({ ...sample(), audio: new Array(17).fill({ src: 'x.wav', start: 0, duration: 1 }) });
});

test('rejects protocols, absolute paths, traversal, and backslashes', () => {
  for (const src of ['https://site/video.mp4', 'file:movie.mp4', '/tmp/x.mp4',
    'C:/movie.mp4', '../movie.mp4', 'assets/../movie.mp4', 'assets\\movie.mp4', '', 'bad\0.mp4']) {
    invalid({ ...sample(), clips: [{ id: 'video', kind: 'video', src, duration: 1 }] }, 'src');
  }
});

test('normalizes bounded clip effects and audio fades without changing old defaults', () => {
  const raw = sample();
  raw.clips[0].effects = { zoom: 1.5, fadeIn: 0.2 };
  raw.audio = [{ src: 'music.wav', start: 0, duration: 2, fadeOut: 0.3 }];
  const project = validateProject(raw);
  assert.deepEqual(project.clips[0].effects, { fadeIn: 0.2, fadeOut: 0, zoom: 1.5, brightness: 0, contrast: 1, saturation: 1 });
  assert.deepEqual({ fadeIn: project.audio[0].fadeIn, fadeOut: project.audio[0].fadeOut }, { fadeIn: 0, fadeOut: 0.3 });
  assert.equal(raw.clips[0].effects.fadeOut, undefined);
  assert.equal(validateProject(sample()).clips[0].effects, undefined);
  for (const effects of [null, { fadeIn: -1 }, { fadeOut: Infinity }, { fadeIn: 1.1, fadeOut: 1 }, { zoom: 0.9 }, { zoom: 2.1 }, { brightness: NaN }, { brightness: 1.1 }, { contrast: -0.1 }, { saturation: 3.1 }, { expression: 'bad' }]) {
    invalid({ ...sample(), clips: [{ ...sample().clips[0], effects }] }, 'effects');
  }
  for (const fades of [{ fadeIn: -1 }, { fadeOut: NaN }, { fadeIn: 0.6, fadeOut: 0.5 }]) {
    invalid({ ...sample(), audio: [{ src: 'music.wav', start: 0, duration: 1, ...fades }] }, 'fade');
  }
});

test('normalizes overlays and rejects unsafe geometry, timing, and extra controls', () => {
  const overlay = { id: 'picture', kind: 'image', src: 'assets/picture.png', start: 0.5, duration: 1, rect: { x: 20, y: 30, width: 300, height: 400 } };
  const normalized = validateProject({ ...sample(), overlays: [overlay] });
  assert.deepEqual(normalized.overlays[0], { ...overlay, opacity: 1 });
  assert.deepEqual(validateProject(sample()).overlays, []);
  const video = { ...overlay, id: 'video', kind: 'video', src: 'assets/video.mp4' };
  assert.equal(validateProject({ ...sample(), overlays: [video] }).overlays[0].in, 0);
  for (const change of [
    { id: 'bad id' }, { kind: 'color' }, { src: '../outside.png' }, { start: -1 }, { duration: 0 },
    { start: 1.5, duration: 1 }, { opacity: -0.1 }, { opacity: 1.1 }, { opacity: NaN }, { in: 0 },
    { volume: 1 }, { rect: null }, { rect: { ...overlay.rect, x: -1 } },
    { rect: { ...overlay.rect, width: 0 } }, { rect: { ...overlay.rect, width: 0.5 } },
    { rect: { ...overlay.rect, x: 700 } }, { rect: { ...overlay.rect, y: 1200 } },
    { rect: { ...overlay.rect, expression: 'bad' } },
  ]) invalid({ ...sample(), overlays: [{ ...overlay, ...change }] }, 'overlays');
  invalid({ ...sample(), overlays: [overlay, overlay] }, 'id');
  invalid({ ...sample(), overlays: null }, 'overlays');
  invalid({ ...sample(), overlays: Array.from({ length: 33 }, (_, i) => ({ ...overlay, id: `image${i}` })) }, 'overlays');
});

function words() {
  return [
    { id: 'w1', text: 'Make', start: 0.2, end: 0.5 },
    { id: 'w2', text: 'something.', start: 0.55, end: 1.1 },
  ];
}

test('word anchors survive normalization and resolve current wording and timing', () => {
  const project = validateProject({ ...sample(), words: words(), captions: [{ fromWord: 'w1', toWord: 'w2' }] });
  const anchored = project.captions[0];
  assert.deepEqual(anchored, { fromWord: 'w1', toWord: 'w2', position: 'bottom', fontSize: 48, color: '#ffffff' });
  assert.deepEqual(validateProject(JSON.parse(JSON.stringify(project))), project);
  assert.deepEqual(resolveCaptions(project), [{ text: 'Make something.', start: 0.2, end: 1.1, position: 'bottom', fontSize: 48, color: '#ffffff' }]);
  project.words[0].text = 'Build';
  project.words[0].start = 0.1;
  project.words[1].end = 1.5;
  const updated = resolveCaptions(validateProject(project))[0];
  assert.equal(updated.text, 'Build something.');
  assert.equal(updated.start, 0.1);
  assert.equal(updated.end, 1.5);
  assert.equal(anchored.start, undefined);
  assert.equal(anchored.text, undefined);
});

test('anchored wording overrides and ordinary timed captions remain independent', () => {
  const raw = { ...sample(), words: words(), captions: [
    { fromWord: 'w1', toWord: 'w1', text: 'An override', position: 'top' },
    { text: 'Unanchored', start: 1.2, end: 2 },
  ] };
  const project = validateProject(raw);
  project.words[0].text = 'Changed';
  const resolved = resolveCaptions(project);
  assert.equal(resolved[0].text, 'An override');
  assert.equal(resolved[0].position, 'top');
  assert.equal(resolved[0].start, 0.2);
  assert.equal(resolved[1].start, 1.2);
  assert.equal(project.captions[0].text, 'An override');
});

test('unknown, reversed, incomplete, and mixed caption anchors are rejected', () => {
  for (const caption of [
    { fromWord: 'missing', toWord: 'w2' }, { fromWord: 'w2', toWord: 'w1' },
    { fromWord: 'w1' }, { toWord: 'w1' }, { fromWord: null, toWord: 'w2' },
    { fromWord: 'w1', toWord: 'w2', start: 0 },
    { fromWord: 'w1', toWord: 'w2', end: 1 },
  ]) invalid({ ...sample(), words: words(), captions: [caption] });
  invalid({ ...sample(), captions: [{ fromWord: 'w1', toWord: 'w2' }] });
});

test('word timestamps require known shapes, unique IDs, chronological non-overlap, and valid text', () => {
  assert.deepEqual(validateProject(sample()).words, []);
  for (const rows of [null, {}, new Array(2001).fill(words()[0]),
    [{ ...words()[0], id: 'bad id' }], [{ ...words()[0], text: '' }],
    [{ ...words()[0], text: 'x'.repeat(201) }], [{ ...words()[0], start: -1 }],
    [{ ...words()[0], end: Infinity }], [{ ...words()[0], end: 2.1 }],
    [{ ...words()[0], end: 0.2 }], [{ ...words()[0], extra: true }],
    [words()[0], { ...words()[1], id: 'w1' }],
    [words()[1], words()[0]],
    [words()[0], { ...words()[1], start: 0.4 }],
  ]) invalid({ ...sample(), words: rows }, 'words');
  // A word ID may equal a clip ID; touching timestamp boundaries are valid.
  validateProject({ ...sample(), words: [{ id: 'intro', text: 'One', start: 0, end: 1 }, { id: 'w2', text: 'Two', start: 1, end: 2 }] });
});

test('derived caption wording cannot exceed the text limit', () => {
  const rows = Array.from({ length: 6 }, (_, i) => ({ id: `w${i}`, text: 'x'.repeat(200), start: i * 0.2, end: (i + 1) * 0.2 }));
  invalid({ ...sample(), words: rows, captions: [{ fromWord: 'w0', toWord: 'w5' }] }, 'text');
  validateProject({ ...sample(), words: rows, captions: [{ fromWord: 'w0', toWord: 'w5', text: 'Short override' }] });
});

function pictureAnchors() {
  return {
    ...sample(), words: words(),
    clips: [
      { id: 'first', kind: 'color', color: '#112233', untilWord: 'w1' },
      { id: 'second', kind: 'color', color: '#445566', untilWord: 'w2' },
      { id: 'tail', kind: 'color', color: '#778899', duration: 0.9 },
    ],
    overlays: [{ id: 'picture', kind: 'image', src: 'picture.png', fromWord: 'w1', toWord: 'w2', rect: { x: 0, y: 0, width: 100, height: 100 } }],
  };
}

test('speech-linked cuts and B-roll retain anchors and resolve current word timing', () => {
  const normalized = validateProject(pictureAnchors());
  assert.equal(normalized.clips[0].untilWord, 'w1');
  assert.equal(normalized.clips[0].duration, undefined);
  assert.equal(normalized.overlays[0].fromWord, 'w1');
  assert.equal(normalized.overlays[0].start, undefined);
  assert.equal(normalized.overlays[0].duration, undefined);
  assert.deepEqual(validateProject(JSON.parse(JSON.stringify(normalized))), normalized);
  const clips = resolveClips(normalized);
  assert.equal(clips[0].untilWord, undefined);
  assert.equal(clips[0].duration, 0.5);
  assert.ok(Math.abs(clips[1].duration - 0.6) < 1e-9);
  const overlay = resolveOverlays(normalized)[0];
  assert.equal(overlay.fromWord, undefined);
  assert.equal(overlay.toWord, undefined);
  assert.equal(overlay.start, 0.2);
  assert.ok(Math.abs(overlay.duration - 0.9) < 1e-9);
  normalized.words[0] = { ...normalized.words[0], text: 'Build', start: 0.1, end: 0.7 };
  normalized.words[1] = { ...normalized.words[1], text: 'better.', start: 0.75, end: 1.4 };
  const retimed = resolveClips(normalized);
  assert.equal(retimed[0].duration, 0.7);
  assert.equal(retimed[1].duration, 0.7);
  assert.equal(retimed[2].duration, 0.9);
  const retimedOverlay = resolveOverlays(normalized)[0];
  assert.equal(retimedOverlay.start, 0.1);
  assert.ok(Math.abs(retimedOverlay.duration - 1.3) < 1e-9);
  assert.equal(normalized.clips[0].duration, undefined);
  assert.equal(normalized.overlays[0].start, undefined);
});

test('picture timing rejects missing, mixed, unknown, backwards, and sub-frame cuts', () => {
  const base = pictureAnchors();
  for (const clips of [
    [{ ...base.clips[0], untilWord: 'missing' }],
    [{ ...base.clips[0], untilWord: null }],
    [{ ...base.clips[0], duration: 1 }],
    [{ id: 'empty', kind: 'color', color: '#112233' }],
    [{ id: 'late', kind: 'color', color: '#112233', duration: 1 }, base.clips[0]],
    [base.clips[0], { ...base.clips[0], id: 'again' }],
    [{ id: 'edge', kind: 'color', color: '#112233', duration: 0.49 }, base.clips[0]],
  ]) invalid({ ...base, clips });
  const tooLong = pictureAnchors();
  tooLong.words[1].end = 600.1;
  invalid(tooLong, 'words');
  invalid({ ...sample(), words: words(), clips: [{ id: 'short', kind: 'color', color: '#112233', duration: 0.5 }] }, 'words');
});

test('anchored clip effects are checked against the freshly resolved duration', () => {
  const p = { ...sample(), words: [{ id: 'end', text: 'End', start: 0, end: 0.5 }], clips: [{ id: 'clip', kind: 'color', color: '#ffffff', untilWord: 'end', effects: { fadeIn: 0.4, fadeOut: 0.2 } }] };
  invalid(p, 'effects');
  p.words[0].end = 0.8;
  const normalized = validateProject(p);
  assert.equal(resolveClips(normalized)[0].duration, 0.8);
  normalized.words[0].end = 0.4;
  invalid(normalized, 'effects');
  const fractional = { ...sample(), canvas: { width: 720, height: 1280, fps: 10 }, words: [{ id: 'end', text: 'End', start: 0.2, end: 0.3 }], clips: [
    { id: 'before', kind: 'color', color: '#ffffff', duration: 0.2 },
    { id: 'last', kind: 'color', color: '#ffffff', untilWord: 'end', effects: { fadeIn: 0.1 } },
  ] };
  validateProject(fractional);
  fractional.clips[0].duration = 0.15;
  fractional.words[0].start = 0.15;
  fractional.words[0].end = 0.24999999999999997;
  invalid(fractional);
});

test('overlay word ranges cannot be mixed with numeric timing or reversed', () => {
  const base = pictureAnchors();
  for (const change of [
    { start: 0 }, { duration: 1 }, { fromWord: 'missing' }, { toWord: undefined },
    { fromWord: 'w2', toWord: 'w1' }, { toWord: null },
  ]) invalid({ ...base, overlays: [{ ...base.overlays[0], ...change }] }, 'overlays');
  const noWords = { ...base, words: [] };
  invalid(noWords);
});

async function directory(t) {
  const root = await mkdtemp(join(tmpdir(), 'agent-video-project-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  return root;
}

test('loads a manifest and verifies regular local media files', async (t) => {
  const root = await directory(t);
  await mkdir(join(root, 'assets'));
  await writeFile(join(root, 'assets', 'clip.mp4'), 'placeholder: probing belongs to the renderer');
  const project = { ...sample(), clips: [{ id: 'clip', kind: 'video', src: 'assets/clip.mp4', duration: 2 }] };
  const file = join(root, 'project.json');
  await writeFile(file, JSON.stringify(project));
  const loaded = await loadProject(file);
  assert.equal(loaded.projectPath, file);
  assert.equal(loaded.root, root);
  assert.equal(loaded.project.clips[0].volume, 1);
});

test('asset preflight is shared by loading and in-memory batch projects', async (t) => {
  const root = await directory(t);
  await writeFile(join(root, 'sound.wav'), 'placeholder');
  const project = validateProject({ ...sample(), audio: [{ src: 'sound.wav', start: 0, duration: 1 }] });
  await validateAssets(project, root);
  project.audio[0].src = 'missing.wav';
  await assert.rejects(validateAssets(project, root), { code: 'INVALID_ASSET' });
});

test('overlay assets undergo the same regular-file and project-confinement checks', async t => {
  const root = await directory(t);
  await writeFile(join(root, 'picture.png'), 'placeholder');
  const project = validateProject({ ...sample(), overlays: [{ id: 'image', kind: 'image', src: 'picture.png', start: 0, duration: 1, rect: { x: 0, y: 0, width: 100, height: 100 } }] });
  await validateAssets(project, root);
  project.overlays[0].src = 'missing.png';
  await assert.rejects(validateAssets(project, root), { code: 'INVALID_ASSET' });
  project.overlays[0].src = '../outside.png';
  await assert.rejects(validateAssets(project, root), { code: 'INVALID_ASSET' });
});

test('reports unreadable manifests, malformed JSON, missing assets, and directory assets', async (t) => {
  const root = await directory(t);
  await assert.rejects(loadProject(join(root, 'absent.json')), { code: 'PROJECT_READ_FAILED' });
  const file = join(root, 'project.json');
  await writeFile(file, '{bad json');
  await assert.rejects(loadProject(file), { code: 'INVALID_PROJECT' });
  const project = { ...sample(), audio: [{ src: 'missing.wav', start: 0, duration: 1 }] };
  await writeFile(file, JSON.stringify(project));
  await assert.rejects(loadProject(file), { code: 'INVALID_ASSET' });
  await mkdir(join(root, 'not-a-file'));
  project.audio[0].src = 'not-a-file';
  await writeFile(file, JSON.stringify(project));
  await assert.rejects(loadProject(file), { code: 'INVALID_ASSET' });
});

test('rejects a media symlink escaping the project root', async (t) => {
  const root = await directory(t);
  const outside = await directory(t);
  await writeFile(join(outside, 'sound.wav'), 'not media');
  try {
    await symlink(outside, join(root, 'linked'), process.platform === 'win32' ? 'junction' : 'dir');
  } catch (error) {
    if (error.code === 'EPERM' || error.code === 'EACCES') return t.skip('OS disallows test symlinks');
    throw error;
  }
  const file = join(root, 'project.json');
  await writeFile(file, JSON.stringify({ ...sample(), audio: [{ src: 'linked/sound.wav', start: 0, duration: 1 }] }));
  await assert.rejects(loadProject(file), { code: 'INVALID_ASSET' });
});
