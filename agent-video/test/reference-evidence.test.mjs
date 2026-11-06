import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';
import test from 'node:test';
import { inspectMedia } from '../src/media.mjs';
import { analyzeReference, referenceRequest, validateReferenceAnalysis } from '../src/reference-evidence.mjs';

function report() {
  return {
    source: 'C:/references/reference.mp4', sha256: 'a'.repeat(64), duration: 10,
    width: 1920, height: 1080, fps: 30000 / 1001, sourceFrameRate: '30000/1001',
    hasVideo: true, hasAudio: true, scenes: [2, 4, 7],
    frames: ['frame-00.png', 'frame-01.png', 'frame-02.png'],
    frameTimes: [1, 3, 9], frameRequestedTimes: [1, 3, 9],
    contactSheet: 'contact-sheet.png', sceneThreshold: 0.3, sceneLimitReached: false,
  };
}

function unknown() { return { status: 'unknown', summary: 'unknown', evidence: [] }; }

function analysis() {
  return {
    version: 1,
    hook: { status: 'observed', summary: 'The opening shows the result.', evidence: [{ start: 0, end: 2, note: 'Agent-authored test annotation of the opening frames.' }] },
    captionStyle: unknown(),
    visualStyle: { status: 'observed', summary: 'The sampled opening uses a plain background.', evidence: [{ start: 0, end: 2, note: 'Agent-authored test annotation of frame 0.' }] },
    audioStyle: unknown(),
    structure: [{ start: 0, end: 2, purpose: 'Opening' }, { start: 2, end: 7, purpose: 'Demonstration' }, { start: 7, end: 10, purpose: 'Close' }],
    uncertainties: ['Caption style is not established by the supplied observations.', 'Audio has not been listened to.'],
    reviewNotes: ['Keep the replacement material editable in Frameflow.'],
  };
}

test('measures shot windows and pacing without inventing semantics or rational frame rates', () => {
  const original = report();
  const evidence = analyzeReference(original);
  assert.equal(evidence.version, 1);
  assert.equal(evidence.source.sha256, original.sha256);
  assert.equal(evidence.source.frameRate, '30000/1001');
  assert.equal(evidence.source.fps, 30000 / 1001);
  assert.deepEqual(evidence.shots, [
    { id: 'shot1', start: 0, end: 2, duration: 2, frameIndices: [0] },
    { id: 'shot2', start: 2, end: 4, duration: 2, frameIndices: [1] },
    { id: 'shot3', start: 4, end: 7, duration: 3, frameIndices: [] },
    { id: 'shot4', start: 7, end: 10, duration: 3, frameIndices: [2] },
  ]);
  assert.deepEqual(evidence.pacing, { cutCount: 3, shotCount: 4, meanShotSeconds: 2.5, medianShotSeconds: 2.5, cutsPerMinute: 18 });
  assert.equal(evidence.confidence.boundaries, 'heuristic');
  assert.equal(evidence.confidence.semantics, 'not-assessed');
  assert.equal(evidence.hook, undefined);
  evidence.frames.push('extra.png');
  assert.equal(original.frames.length, 3);
  delete original.sourceFrameRate;
  const decimalOnly = analyzeReference(original);
  assert.equal(decimalOnly.source.frameRate, null);
  assert.match(decimalOnly.limits.join(' '), /rational/i);
});

test('handles a continuous shot and reports censored or sparse measurement coverage', () => {
  const continuous = analyzeReference({ ...report(), scenes: [], sceneLimitReached: true, frameTimes: [0, 0, 0] });
  assert.deepEqual(continuous.pacing, { cutCount: 0, shotCount: 1, meanShotSeconds: 10, medianShotSeconds: 10, cutsPerMinute: 0 });
  assert.deepEqual(continuous.shots[0].frameIndices, [0, 1, 2]);
  assert.equal(continuous.cutDetection.limitReached, true);
  assert.match(continuous.limits.join(' '), /limit/i);
  assert.match(continuous.limits.join(' '), /seek/i);
});

test('rejects malformed report identities, cut boundaries and frame observations', () => {
  for (const change of [
    { source: '' }, { sha256: 'invalid' }, { duration: 0 }, { duration: 601 }, { fps: NaN },
    { sourceFrameRate: '0/0' }, { hasVideo: false }, { hasAudio: 'yes' }, { width: 0 },
    { scenes: [2, 2] }, { scenes: [4, 2] }, { scenes: [0] }, { scenes: [10] },
    { scenes: [Infinity] }, { frames: [] }, { frameTimes: [1] },
    { frameRequestedTimes: [-1, 3, 9] }, { frameTimes: [1, 3, 10] },
    { contactSheet: null }, { sceneThreshold: 2 }, { sceneLimitReached: 'no' },
  ]) assert.throws(() => analyzeReference({ ...report(), ...change }), { code: 'INVALID_REFERENCE_REPORT' });
});

test('normalizes authored observations and explicit unknowns without mutating the analysis', () => {
  const raw = analysis();
  raw.hook.summary = '  The opening shows the result.  ';
  const normalized = validateReferenceAnalysis(raw, analyzeReference(report()));
  assert.equal(normalized.hook.summary, 'The opening shows the result.');
  assert.equal(raw.hook.summary.startsWith('  '), true);
  assert.deepEqual(normalized.captionStyle, unknown());
  assert.deepEqual(validateReferenceAnalysis(JSON.parse(JSON.stringify(normalized)), analyzeReference(report())), normalized);
  normalized.hook.evidence[0].note = 'changed';
  assert.notEqual(raw.hook.evidence[0].note, 'changed');
  const partial = { ...analysis(), structure: [], hook: unknown(), visualStyle: unknown() };
  validateReferenceAnalysis(partial, analyzeReference(report()));
});

test('observed and unknown facets require honest, explicit evidence semantics', () => {
  const evidence = analyzeReference(report());
  for (const hook of [
    { status: 'observed', summary: 'A confident guess', evidence: [] },
    { status: 'observed', summary: 'unknown', evidence: [{ start: 0, end: 1, note: 'A frame' }] },
    { status: 'unknown', summary: 'Probably a bold hook', evidence: [] },
    { status: 'unknown', summary: 'unknown', evidence: [{ start: 0, end: 1, note: 'A frame' }] },
    { summary: 'unknown', evidence: [] },
    { status: 'inferred', summary: 'A guess', evidence: [] },
  ]) assert.throws(() => validateReferenceAnalysis({ ...analysis(), hook }, evidence), { code: 'INVALID_REFERENCE_ANALYSIS' });
});

test('analysis intervals stay on the source clock and structure remains ordered', () => {
  const evidence = analyzeReference(report());
  for (const intervals of [
    [{ start: -1, end: 1, note: 'bad' }], [{ start: 0, end: 11, note: 'bad' }],
    [{ start: 1, end: 1, note: 'bad' }], [{ start: 0, end: NaN, note: 'bad' }],
    [{ start: 2, end: 3, note: 'later' }, { start: 0, end: 1, note: 'earlier' }],
  ]) assert.throws(() => validateReferenceAnalysis({ ...analysis(), hook: { status: 'observed', summary: 'Opening', evidence: intervals } }, evidence), { code: 'INVALID_REFERENCE_ANALYSIS' });
  for (const structure of [
    [{ start: 0, end: 3, purpose: 'one' }, { start: 2, end: 4, purpose: 'overlapping' }],
    [{ start: 9, end: 11, purpose: 'outside' }], [{ start: 0, end: 1, purpose: '' }],
  ]) assert.throws(() => validateReferenceAnalysis({ ...analysis(), structure }, evidence), { code: 'INVALID_REFERENCE_ANALYSIS' });
});

test('analysis rejects unknown fields, dangerous text and malformed review arrays', () => {
  const evidence = analyzeReference(report());
  for (const value of [
    null, { ...analysis(), version: 2 }, { ...analysis(), generatedNarration: 'invented' },
    { ...analysis(), hook: { ...analysis().hook, style: 'extra' } },
    { ...analysis(), hook: { ...analysis().hook, evidence: [{ start: 0, end: 1, note: 'x', guessed: true }] } },
    { ...analysis(), reviewNotes: ['bad\0text'] }, { ...analysis(), uncertainties: 'none' },
  ]) assert.throws(() => validateReferenceAnalysis(value, evidence), { code: 'INVALID_REFERENCE_ANALYSIS' });
});

test('agent request describes exact authored contracts and delegates editable Frameflow work', () => {
  const request = referenceRequest({ version: 1, evidence: analyzeReference(report()),
    brief: { title: 'Replacement subject', format: 'reel', aspect: '9:16', target_seconds: 10, audience: 'Viewers', tone: 'Clear', summary: 'Use supplied media.' },
    inputs: { footage: [{ name: 'supplied.mp4', source: 'C:/assets/supplied.mp4', duration: 10 }], assets: [], music: [] }, timings: {},
  });
  assert.match(request, /analysis\.json/);
  assert.match(request, /concepts\.json/);
  assert.match(request, /exactly 2 or 3/i);
  assert.match(request, /frame-00\.png/);
  assert.match(request, /contact-sheet\.png/);
  assert.match(request, /captionStyle/);
  assert.match(request, /status/);
  assert.match(request, /storyboard/);
  assert.match(request, /source.clock|source clock/i);
  assert.match(request, /measured pauses/i);
  assert.match(request, /narration/i);
  assert.match(request, /editable/i);
  assert.match(request, /unknown/);
});

test('actual inspected fixture yields measured shot lengths and frame associations', async t => {
  const root = await mkdtemp(join(tmpdir(), 'agent-video-reference-evidence-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const workDir = join(root, 'inspection'); await mkdir(workDir);
  const source = join(root, 'fixture.mp4');
  await promisify(execFile)(process.env.FFMPEG_PATH || 'ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'color=c=red:s=160x90:r=10:d=0.6', '-f', 'lavfi', '-i', 'color=c=blue:s=160x90:r=10:d=0.4', '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[video]', '-map', '[video]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-n', source], { windowsHide: true });
  const measured = await inspectMedia(source, { workDir, sceneThreshold: 0.1 });
  const evidence = analyzeReference(measured);
  assert.equal(evidence.pacing.cutCount, 1);
  assert.equal(evidence.shots.length, 2);
  assert.ok(Math.abs(evidence.shots[0].duration - 0.6) < 0.001);
  assert.ok(Math.abs(evidence.shots[1].duration - 0.4) < 0.001);
  assert.equal(evidence.pacing.meanShotSeconds, 0.5);
  assert.deepEqual(evidence.shots.map(shot => shot.frameIndices), [[0], [1]]);
});
