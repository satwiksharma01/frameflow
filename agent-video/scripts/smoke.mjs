import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { loadProject, resolveClips, validateProject } from '../src/project.mjs';
import { probeMedia } from '../src/render.mjs';
import { runJob } from '../src/jobs.mjs';

const exec = promisify(execFile);
const cli = fileURLToPath(new URL('../bin/agent-video.mjs', import.meta.url));
const [sourceFile, destination] = process.argv.slice(2);
assert.ok(sourceFile && destination, 'Usage: node scripts/smoke.mjs <local-speech-video> <new-output-directory>');
assert.ok(process.env.WHISPER_CPP_PATH && process.env.WHISPER_CPP_MODEL, 'Set the local whisper.cpp executable and model paths first.');
const source = resolve(sourceFile);
const directory = resolve(destination);
await mkdir(dirname(directory), { recursive: true });
await mkdir(directory);

async function call(args) {
  const { stdout } = await exec(process.execPath, [cli, ...args, '--json'], { windowsHide: true, maxBuffer: 8 * 1024 * 1024 });
  const result = JSON.parse(stdout);
  assert.equal(result.ok, true, stdout);
  return result;
}
async function save(file, value) { await writeFile(file, JSON.stringify(value, null, 2) + '\n', { flag: 'wx' }); }

const inspection = (await call(['inspect', source, '--out-dir', join(directory, 'evidence'), '--scene-threshold', '0.02'])).inspection;
assert.equal(inspection.hasAudio, true);
assert.equal(inspection.hasVideo, true);
assert.ok(inspection.frames.length > 0);
const reconstructed = await call(['reconstruct', source, '--out-dir', join(directory, 'project'), '--scene-threshold', '0.02']);
const base = await loadProject(reconstructed.project);
const supplied = resolve(base.root, base.project.clips[0].src);
const transcript = (await call(['transcribe', supplied, '--out-dir', join(directory, 'speech')])).transcript;
assert.ok(transcript.wordCount > 0);
const timedFile = join(base.root, 'timed.json');
await call(['captions', reconstructed.project, '--words', transcript.words, '--out', timedFile, '--group-size', '4']);
const loaded = await loadProject(timedFile);
const project = loaded.project;
const fontSize = Math.max(12, Math.min(40, Math.round(project.canvas.height * 0.07)));
project.captions = project.captions.map(caption => ({ ...caption, fontSize }));
const duration = resolveClips(project).reduce((sum, clip) => sum + clip.duration, 0);
await copyFile(inspection.frames.at(-1), join(base.root, 'assets', 'insert.png'));
const first = project.words[0];
const last = project.words[Math.min(3, project.words.length - 1)];
project.overlays = [{ id: 'supplied-broll', kind: 'image', src: 'assets/insert.png', fromWord: first.id, toWord: last.id, opacity: 0.8, rect: { x: 8, y: 8, width: Math.max(16, Math.floor(project.canvas.width / 3)), height: Math.max(16, Math.floor(project.canvas.height / 3)) } }];
project.clips[0].effects = { fadeIn: Math.min(0.2, project.clips[0].duration / 2), contrast: 1.1, saturation: 0.9 };
if (project.clips.length > 1) {
  const boundary = resolveClips(project)[0].duration;
  const cue = [...project.words].sort((a, b) => Math.abs(a.end - boundary) - Math.abs(b.end - boundary))[0];
  if (cue.end >= 1 / project.canvas.fps && duration + cue.end - boundary >= project.words.at(-1).end) {
    project.clips[0].untilWord = cue.id;
    delete project.clips[0].duration;
  }
}
const edited = validateProject(project);
const editedFile = join(base.root, 'edited.json');
await save(editedFile, edited);
const plan = await call(['plan', editedFile]);
assert.equal(plan.overlayCount, 1);
assert.ok(plan.captions[0].text);
const variants = join(directory, 'variants.json');
await save(variants, [
  { id: 'original', patch: {} },
  { id: 'alternate', patch: { title: `${edited.title} — alternate`, captions: edited.captions.map(caption => ({ ...caption, color: '#FFE6AA' })) } },
]);
const batch = (await call(['batch', editedFile, '--variants', variants, '--out-dir', join(directory, 'cuts')])).batch;
assert.equal(batch.status, 'succeeded');
assert.equal(batch.variants[1].artifact.cache.hits, edited.clips.length);
const checkedBatch = (await call(['resume-batch', batch.directory])).batch;
assert.deepEqual(checkedBatch.variants.map(entry => entry.jobId), batch.variants.map(entry => entry.jobId));

let failedJob;
await assert.rejects(runJob(await loadProject(editedFile), join(directory, 'resumed.mp4'), {
  onProgress(progress) {
    failedJob = progress.jobId;
    if (progress.stage === 'compose' && progress.completed === 0) throw new Error('Verification interruption after clip encoding');
  },
}), /Verification interruption/);
const resumed = (await call(['resume', base.root, '--job', failedJob])).job;
assert.equal(resumed.resumedFrom, failedJob);
assert.equal(resumed.artifact.cache.hits, edited.clips.length);
assert.equal((await call(['status', base.root, '--job', failedJob])).job.status, 'failed');
const outputs = [];
for (const file of [batch.variants[0].output, batch.variants[1].output, resumed.output]) {
  const metadata = await probeMedia(file);
  const video = metadata.streams.find(stream => stream.codec_type === 'video');
  assert.equal(video.width, edited.canvas.width);
  assert.equal(video.height, edited.canvas.height);
  assert.ok(metadata.streams.some(stream => stream.codec_type === 'audio'));
  outputs.push({ file, duration: Number(metadata.format.duration), width: video.width, height: video.height, frames: video.nb_frames });
}
const report = { source, directory, inspection, reconstructed, transcript, editedProject: editedFile, plan, batch, failedJob, resumed, outputs };
await save(join(directory, 'verification.json'), report);
console.log(JSON.stringify({ ok: true, report: join(directory, 'verification.json'), words: transcript.wordCount, outputs, resumedCache: resumed.artifact.cache }));
