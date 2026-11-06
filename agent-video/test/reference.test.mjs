import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';
import test from 'node:test';
import { checkReference, exportFrameflow, prepareReference, readReferenceJson, sampleReference, verifyHandoffSource } from '../src/reference.mjs';

const exec = promisify(execFile);

test('handoff refuses an unprepared canonical media target and only permits new composition entry points', () => {
  const pin = { path: 'new-target.mp4', bytes: 5, sha256: 'a'.repeat(64) };
  assert.throws(() => verifyHandoffSource(pin, undefined, 'clip'), { code: 'SOURCE_CHANGED' });
  assert.throws(() => verifyHandoffSource(pin, { ...pin, sha256: 'b'.repeat(64) }, 'clip'), { code: 'SOURCE_CHANGED' });
  assert.doesNotThrow(() => verifyHandoffSource(pin, { ...pin }, 'clip'));
  assert.doesNotThrow(() => verifyHandoffSource(pin, undefined, 'composition'));
});
async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'agent-video-reference-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const reference = join(root, 'reference.mp4');
  const target = join(root, 'supplied.mp4');
  for (const [file, color] of [[reference, 'red'], [target, 'blue']]) {
    await exec(process.env.FFMPEG_PATH || 'ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', `color=c=${color}:s=160x240:r=10:d=1`, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-n', file], { windowsHide: true });
  }
  const inputsFile = join(root, 'inputs.json');
  const briefFile = join(root, 'brief.json');
  await writeFile(inputsFile, JSON.stringify({ footage: [{ name: 'recording.mp4', source: 'supplied.mp4', duration: 1 }], assets: [], music: [] }));
  await writeFile(briefFile, JSON.stringify({ title: 'Synthetic fixture', format: 'reel', aspect: '9:16', target_seconds: 1, fps: 30, audience: 'Developers', tone: 'Clear', summary: 'A deliberately simple local fixture, not an artistic benchmark.' }));
  const sessionDir = join(root, 'session');
  return { root, reference, target, inputsFile, briefFile, sessionDir };
}

function analysis(duration = 1) {
  const unknown = () => ({ status: 'unknown', summary: 'unknown', evidence: [] });
  return {
    version: 1, hook: unknown(), captionStyle: unknown(), visualStyle: unknown(), audioStyle: unknown(),
    structure: [{ start: 0, end: duration, purpose: 'A synthetic color-only test shot.' }],
    uncertainties: ['This fixture establishes neither a semantic hook nor caption design.'],
    reviewNotes: ['Human-authored test observations; not automatic creative analysis.'],
  };
}

async function authorSession(sessionDir, concepts = undefined) {
  await writeFile(join(sessionDir, 'analysis.json'), JSON.stringify(analysis()));
  const storyboard = { script: 'Use the existing supplied recording.', scenes: [{ visual: { type: 'footage', source: 'recording.mp4', start: 0, end: 1 }, reason: 'Keep this measured full source interval.' }] };
  await writeFile(join(sessionDir, 'concepts.json'), JSON.stringify({ version: 1, concepts: concepts ?? [
    { id: 'direct', title: 'Direct performance', summary: 'A straightforward adaptation using the supplied shot.', adaptation: 'Use the selected recording without inventing any replacement media.', storyboard },
    { id: 'alternate', title: 'Alternate proposal', summary: 'A second explicit proposal for human review.', adaptation: 'Retain the same supplied performance; creative distinction remains a review decision.', storyboard },
  ] }));
}

test('JSON boundary rejects oversized/malformed/nonregular documents and confines fixed session files', async t => {
  const { root } = await fixture(t);
  const file = join(root, 'small.json');
  await writeFile(file, '{bad');
  await assert.rejects(readReferenceJson(file), { code: 'REFERENCE_READ_FAILED' });
  await writeFile(file, ' '.repeat(2 * 1024 * 1024 + 1));
  await assert.rejects(readReferenceJson(file), { code: 'REFERENCE_READ_FAILED' });
  await assert.rejects(readReferenceJson(root), { code: 'REFERENCE_READ_FAILED' });
  await writeFile(file, '{}');
  const sibling = join(root, 'owned'); await mkdir(sibling);
  await assert.rejects(readReferenceJson(file, { root: sibling }), { code: 'REFERENCE_READ_FAILED' });
});

test('preparation records measured evidence and requests agent analysis without copying the reference into target media', async t => {
  const data = await fixture(t);
  const prepared = await prepareReference(data.reference, { inputsFile: data.inputsFile, briefFile: data.briefFile, outDir: data.sessionDir });
  const session = JSON.parse(await readFile(prepared.session, 'utf8'));
  assert.equal(session.version, 1);
  assert.equal(session.inputs.footage[0].source, data.target);
  assert.equal(session.evidence.source.path, data.reference);
  assert.match(session.evidence.source.sha256, /^[0-9a-f]{64}$/);
  assert.ok((await readFile(prepared.request, 'utf8')).includes('analysis.json'));
  assert.ok(!(await readdir(data.sessionDir)).includes('assets'));
  await assert.rejects(prepareReference(data.reference, { inputsFile: data.inputsFile, briefFile: data.briefFile, outDir: data.sessionDir }), { code: 'OUTPUT_EXISTS' });
  await assert.rejects(checkReference(data.sessionDir));
});

test('check/export validate authored documents and preserve source-clock mappings, requirements and approvals', async t => {
  const data = await fixture(t);
  await prepareReference(data.reference, { inputsFile: data.inputsFile, briefFile: data.briefFile, outDir: data.sessionDir });
  await authorSession(data.sessionDir);
  const checked = await checkReference(data.sessionDir);
  assert.equal(checked.concepts.length, 2);
  assert.equal(checked.concepts[0].timeline[0].source, data.target);
  const destination = join(data.root, 'handoff');
  const exported = await exportFrameflow(data.sessionDir, { concept: 'direct', outDir: destination });
  const manifest = JSON.parse(await readFile(exported.manifest, 'utf8'));
  assert.equal(manifest.version, 1);
  assert.equal(manifest.timeline[0].sourceIn, 0);
  assert.equal(manifest.timeline[0].sourceOut, 1);
  assert.ok(manifest.requirements.includes('native-project-export'));
  assert.equal(manifest.approvals.frameflowBuild, 'pending');
  assert.deepEqual((await readdir(destination)).sort(), ['brief.json', 'inputs.json', 'manifest.json', 'reference-analysis.json', 'source-timings.json', 'storyboard.json']);
  assert.deepEqual(JSON.parse(await readFile(exported.timings, 'utf8')), checked.session.timings);
  assert.ok(manifest.documents.some(document => document.file === 'source-timings.json'));
  assert.deepEqual(manifest.evidenceFiles, checked.session.provenance.evidenceFiles);
  await assert.rejects(exportFrameflow(data.sessionDir, { concept: 'direct', outDir: destination }), { code: 'OUTPUT_EXISTS' });
  await assert.rejects(exportFrameflow(data.sessionDir, { concept: 'missing', outDir: join(data.root, 'missing') }), { code: 'CONCEPT_NOT_FOUND' });
});

test('samples preserve complete initial scenes and refuse to introduce a partial scene cut', async t => {
  const data = await fixture(t);
  await prepareReference(data.reference, { inputsFile: data.inputsFile, briefFile: data.briefFile, outDir: data.sessionDir });
  await authorSession(data.sessionDir);
  const concepts = await readReferenceJson(join(data.sessionDir, 'concepts.json'));
  for (const concept of concepts.concepts) concept.storyboard.scenes.push({ ...concept.storyboard.scenes[0], reason: 'A second complete interval for the prefix-selection test.' });
  await writeFile(join(data.sessionDir, 'concepts.json'), JSON.stringify(concepts));
  await assert.rejects(sampleReference(data.sessionDir, { concept: 'direct', seconds: 0.5, outDir: join(data.root, 'short') }), { code: 'SAMPLE_TOO_SHORT' });
  const result = await sampleReference(data.sessionDir, { concept: 'direct', seconds: 1, outDir: join(data.root, 'sample') });
  const storyboard = JSON.parse(await readFile(result.storyboard, 'utf8'));
  const manifest = JSON.parse(await readFile(result.manifest, 'utf8'));
  assert.equal(storyboard.scenes.length, 1);
  assert.equal(storyboard.scenes[0].visual.start, 0);
  assert.equal(storyboard.scenes[0].visual.end, 1);
  assert.deepEqual(manifest.sample, { maximumSeconds: 1, originalScenes: 2, retainedScenes: 1 });
  assert.ok(!manifest.warnings.some(warning => warning.includes('duration 2s')));
});

test('changed source bytes, malformed session versions and invalid concept counts block handoff', async t => {
  const data = await fixture(t);
  await prepareReference(data.reference, { inputsFile: data.inputsFile, briefFile: data.briefFile, outDir: data.sessionDir });
  await authorSession(data.sessionDir);
  const concept = (await readReferenceJson(join(data.sessionDir, 'concepts.json'))).concepts[0];
  await writeFile(join(data.sessionDir, 'concepts.json'), JSON.stringify({ version: 1, concepts: [concept] }));
  await assert.rejects(checkReference(data.sessionDir), { code: 'INVALID_CONCEPTS' });
  await authorSession(data.sessionDir);
  await writeFile(data.reference, 'changed source bytes');
  await assert.rejects(checkReference(data.sessionDir), { code: 'SOURCE_CHANGED' });
  const session = await readReferenceJson(join(data.sessionDir, 'session.json'));
  session.version = 2;
  await writeFile(join(data.sessionDir, 'session.json'), JSON.stringify(session));
  await assert.rejects(checkReference(data.sessionDir), { code: 'INVALID_REFERENCE_SESSION' });
});

test('supplied-media changes and evidence modifications are detected before export', async t => {
  const data = await fixture(t);
  const sourceBytes = await readFile(data.target);
  await prepareReference(data.reference, { inputsFile: data.inputsFile, briefFile: data.briefFile, outDir: data.sessionDir });
  await authorSession(data.sessionDir);
  await writeFile(data.target, 'different supplied bytes');
  await assert.rejects(checkReference(data.sessionDir), { code: 'SOURCE_CHANGED' });
  await writeFile(data.target, sourceBytes);
  const session = await readReferenceJson(join(data.sessionDir, 'session.json'));
  await writeFile(session.evidence.frames[0], 'changed evidence PNG');
  await assert.rejects(exportFrameflow(data.sessionDir, { concept: 'direct', outDir: join(data.root, 'blocked') }), { code: 'SOURCE_CHANGED' });
  await assert.rejects(readdir(join(data.root, 'blocked')), { code: 'ENOENT' });
});

test('explicit reference reuse is disclosed while no replacement is added automatically', async t => {
  const data = await fixture(t);
  const inputs = await readReferenceJson(data.inputsFile);
  inputs.footage[0].source = 'reference.mp4';
  await writeFile(data.inputsFile, JSON.stringify(inputs));
  const prepared = await prepareReference(data.reference, { inputsFile: data.inputsFile, briefFile: data.briefFile, outDir: data.sessionDir });
  assert.ok(prepared.warnings.some(warning => warning.includes('explicitly reuses')));
  await authorSession(data.sessionDir);
  const checked = await checkReference(data.sessionDir);
  assert.equal(checked.session.inputs.footage.length, 1);
  assert.equal(checked.session.inputs.footage[0].source, data.reference);
  assert.ok(checked.warnings.some(warning => warning.includes('explicitly reuses')));
});

test('invalid timings and pre-cancelled preparation do not create output state', async t => {
  const data = await fixture(t);
  const timingsFile = join(data.root, 'timings.json');
  await writeFile(timingsFile, 'null');
  await assert.rejects(prepareReference(data.reference, { inputsFile: data.inputsFile, briefFile: data.briefFile, timingsFile, outDir: data.sessionDir }));
  await assert.rejects(readdir(data.sessionDir), { code: 'ENOENT' });
  const controller = new AbortController(); controller.abort();
  await assert.rejects(prepareReference(data.reference, { inputsFile: data.inputsFile, briefFile: data.briefFile, outDir: data.sessionDir, signal: controller.signal }), { code: 'CANCELLED' });
  await assert.rejects(readdir(data.sessionDir), { code: 'ENOENT' });
});
