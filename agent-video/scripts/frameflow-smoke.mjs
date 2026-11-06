import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const exec = promisify(execFile);
const cli = fileURLToPath(new URL('../bin/agent-video.mjs', import.meta.url));
const [destination, frameflow] = process.argv.slice(2);
assert.ok(destination, 'Usage: node scripts/frameflow-smoke.mjs <new-output-directory> [read-only-Frameflow-directory]');
const root = resolve(destination);
await mkdir(dirname(root), { recursive: true });
await mkdir(root);
const save = (file, value) => writeFile(file, JSON.stringify(value, null, 2) + '\n', { flag: 'wx' });
const digest = async file => createHash('sha256').update(await readFile(file)).digest('hex');
async function call(args) {
  const { stdout } = await exec(process.execPath, [cli, ...args, '--json'], { windowsHide: true, maxBuffer: 8 * 1024 * 1024 });
  const result = JSON.parse(stdout);
  assert.equal(result.ok, true, stdout);
  return result;
}
async function ffmpeg(args) {
  return exec(process.env.FFMPEG_PATH || 'ffmpeg', ['-v', 'error', '-nostdin', ...args], { windowsHide: true });
}

// These are labeled synthetic pictures and tones, not reference-style inference.
const reference = join(root, 'reference.mp4');
const footage = join(root, 'supplied.mp4');
const insert = join(root, 'supplied-still.png');
await ffmpeg(['-f', 'lavfi', '-i', 'color=c=navy:s=320x180:r=30:d=2', '-f', 'lavfi', '-i', 'color=c=orange:s=320x180:r=30:d=2',
  '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[v]', '-map', '[v]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-n', reference]);
await ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=4', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=4',
  '-af', "volume=enable='between(t,0.8,1.4)':volume=0", '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-n', footage]);
await ffmpeg(['-i', footage, '-frames:v', '1', '-threads', '1', '-n', insert]);
const measured = await exec(process.env.FFMPEG_PATH || 'ffmpeg', ['-hide_banner', '-nostdin', '-i', footage, '-vn', '-af', 'silencedetect=n=-40dB:d=0.1', '-f', 'null', '-'], { windowsHide: true });
const starts = [...measured.stderr.matchAll(/silence_start: ([\d.]+)/g)].map(match => Number(match[1]));
const ends = [...measured.stderr.matchAll(/silence_end: ([\d.]+)/g)].map(match => Number(match[1]));
assert.equal(starts.length, 1, measured.stderr);
assert.equal(ends.length, 1, measured.stderr);
assert.ok(starts[0] < 1.05 && ends[0] > 1.15, 'The fixture needs a real measured pause around 1.1 seconds');
const timings = { 'supplied.mp4': { pauses: [{ start: starts[0], end: ends[0] }], words: [] } };
const brief = { title: 'Reference handoff verification', format: 'demonstration', aspect: '16:9', fps: 30, target_seconds: 4,
  audience: 'developers', tone: 'clear', summary: 'A synthetic demonstration of a source-safe editable handoff.' };
const inputs = { prompt: 'Use a result-first structure with different supplied material.', script: null,
  footage: [{ name: 'supplied.mp4', source: footage, duration: 4 }], assets: [{ path: insert, kind: 'image' }], music: [] };
for (const [name, value] of Object.entries({ brief, inputs, timings })) await save(join(root, `${name}.json`), value);
const prepared = await call(['reference-prepare', reference, '--inputs', join(root, 'inputs.json'), '--brief', join(root, 'brief.json'),
  '--timings', join(root, 'timings.json'), '--out-dir', join(root, 'session')]);
const observed = { status: 'observed', summary: 'The opening is a navy card before a switch to orange.', evidence: [{ start: 0, end: 2, note: 'Known synthetic fixture, inspected frame sequence.' }] };
const unknown = { status: 'unknown', summary: 'unknown', evidence: [] };
await save(join(root, 'session', 'analysis.json'), { version: 1, hook: observed, captionStyle: unknown, visualStyle: observed, audioStyle: unknown,
  structure: [{ start: 0, end: 2, purpose: 'Opening card' }, { start: 2, end: 4, purpose: 'Second card' }],
  uncertainties: ['No semantic hook, real speech, or caption style is established by this synthetic fixture.'], reviewNotes: ['The future native editor build remains untested here.'] });
const board = { script: 'Supplied test footage with an opening separated at a measured pause.', spoken_captions: false,
  scenes: [
    { visual: { type: 'footage', source: 'supplied.mp4', start: 0, end: 1.1 },
      broll: [{ path: insert, duration: 0.4 }], cards: [{ kind: 'product', text: 'Synthetic result', duration: 0.4 }], reason: 'A short result-first opening' },
    { visual: { type: 'footage', source: 'supplied.mp4', start: 1.1, end: 4 }, reason: 'Continue the demonstration' },
  ] };
const alternate = { ...board, script: 'Begin with context, then show the result.', scenes: [...board.scenes].reverse() };
await save(join(root, 'session', 'concepts.json'), { version: 1, concepts: [
  { id: 'result-first', title: 'Result first', summary: 'Open with the result.', adaptation: 'Use different supplied footage and a measured pause.', storyboard: board },
  { id: 'context-first', title: 'Context first', summary: 'Open with the longer demonstration.', adaptation: 'Reverse the emphasis without copying the reference footage.', storyboard: alternate },
] });
const checked = await call(['reference-check', join(root, 'session')]);
const exported = await call(['frameflow-export', join(root, 'session'), '--concept', 'result-first', '--out-dir', join(root, 'handoff')]);
const sample = await call(['reference-sample', join(root, 'session'), '--concept', 'result-first', '--seconds', '1.5', '--out-dir', join(root, 'sample')]);
const sampleBoard = JSON.parse(await readFile(sample.storyboard, 'utf8'));
assert.equal(sampleBoard.scenes.length, 1);
const direct = await call(['frameflow-check', exported.storyboard, '--inputs', exported.inputs, '--brief', exported.brief, '--timings', exported.timings]);
assert.equal(direct.duration, 4);
assert.equal(direct.timeline.length, 2);
assert.ok(direct.requirements.includes('broll-placement'));
assert.ok(direct.requirements.includes('card-rendering'));
const sourcesAfter = await Promise.all([reference, footage].map(digest));
assert.notEqual(sourcesAfter[0], sourcesAfter[1]);

// Exercise the source cut only; B-roll/cards are declarations for the future native build.
const previewProject = join(root, 'preview-project');
await mkdir(join(previewProject, 'assets'), { recursive: true });
await copyFile(footage, join(previewProject, 'assets', 'supplied.mp4'));
await save(join(previewProject, 'project.json'), { version: 1, title: 'Synthetic sample preview', canvas: { width: 320, height: 180, fps: 30 },
  clips: [{ id: 'opening', kind: 'video', src: 'assets/supplied.mp4', in: 0, duration: 1.1 }] });
const preview = await call(['render', join(previewProject, 'project.json'), '--out', join(root, 'sample-preview.mp4')]);
await ffmpeg(['-i', join(root, 'sample-preview.mp4'), '-frames:v', '1', '-threads', '1', '-n', join(root, 'sample-preview.png')]);
let compatibility = { checked: false, reason: 'No Frameflow directory supplied; no native editor build was run.' };
if (frameflow) {
  const script = 'import json,sys\nfrom pathlib import Path\nfrom jsonschema import Draft202012Validator\nroot=Path(sys.argv[1])\nfor kind,file in [("storyboard",sys.argv[2]),("brief",sys.argv[3]),("storyboard",sys.argv[4])]:\n schema=json.loads((root/"project"/"schema"/(kind+".schema.json")).read_text(encoding="utf-8"))\n value=json.loads(Path(file).read_text(encoding="utf-8"))\n Draft202012Validator(schema).validate(value)\nprint("Actual Frameflow schemas accepted full/sample storyboards and brief")';
  const result = await exec(process.env.PYTHON_PATH || 'python', ['-B', '-X', 'utf8', '-c', script, resolve(frameflow), exported.storyboard, exported.brief, sample.storyboard], { windowsHide: true });
  compatibility = { checked: true, result: result.stdout.trim(), schemas: await Promise.all(['storyboard', 'brief'].map(async name => ({ name, sha256: await digest(join(resolve(frameflow), 'project', 'schema', `${name}.schema.json`)) }))), nativeEditorBuild: false };
}
await save(join(root, 'verification.json'), { version: 1, fixture: 'Synthetic color cards/test pattern and tone with an actually measured pause; no recognition or semantic recreation benchmark.',
  prepared, conceptCount: checked.concepts.length, measuredPauses: timings, exported, sample, preview: preview.job.output,
  previewScope: 'Source-cut fixture only. B-roll/cards are validated declarations for a future native Frameflow build.', compatibility, sourceSha256: sourcesAfter });
process.stdout.write(JSON.stringify({ ok: true, verification: join(root, 'verification.json'), storyboard: exported.storyboard, sample: sample.storyboard, preview: preview.job.output, compatibility }, null, 2) + '\n');
