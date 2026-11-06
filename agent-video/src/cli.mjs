import { mkdir, readFile, realpath, stat, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { loadProject, resolveCaptions, resolveClips, resolveOverlays, validateAssets, validateProject } from './project.mjs';
import { readJob, runJob } from './jobs.mjs';
import { groupWordCaptions } from './captions.mjs';
import { runBatch } from './batch.mjs';

const help = `Agent Video — local video tools for coding agents

  agent-video init [directory]                    Create an editable demo project
  agent-video doctor                              Check FFmpeg and FFprobe
  agent-video check project.json                   Validate project and local assets
  agent-video plan project.json                    Show the timeline without rendering
  agent-video render project.json --out video.mp4  Render; never overwrite an output
  agent-video status project.json --job UUID       Read a render's saved status
  agent-video variant project.json --patch edits.json --out variant.json
  agent-video captions project.json --words words.json --out timed.json [--group-size 4]
  agent-video batch project.json --variants variants.json --out-dir new-directory
  agent-video inspect media.mp4 --out-dir evidence [--scene-threshold 0.3]
  agent-video reconstruct media.mp4 --out-dir new-project [--scene-threshold 0.3]
  agent-video transcribe media.mp4 --out-dir transcript [--language en]
  agent-video resume project-directory --job UUID [--out new-video.mp4]
  agent-video resume-batch batch-directory
  agent-video reference-prepare reference.mp4 --inputs inputs.json --brief brief.json --out-dir session [--timings timings.json]
  agent-video reference-check session
  agent-video frameflow-check storyboard.json --inputs inputs.json --brief brief.json [--timings timings.json]
  agent-video frameflow-export session --concept concept-id --out-dir handoff
  agent-video reference-sample session --concept concept-id --seconds 10 --out-dir sample

Add --json for structured output. Paths in commands are relative to the working
directory. Media paths inside a project are relative to that project's directory.
Variants stay beside the original project; supplied top-level fields replace the
original fields, including whole arrays. Use check before rendering a variant.
`;

function fail(code, message) { throw Object.assign(new Error(message), { code }); }

const valueOptions = ['--out', '--patch', '--job', '--words', '--group-size', '--variants', '--out-dir', '--scene-threshold', '--language', '--inputs', '--brief', '--timings', '--concept', '--seconds'];

function parse(argv) {
  const options = {};
  const positional = [];
  for (let i = 0; i < argv.length; i++) {
    const word = argv[i];
    if (word === '--json' || word === '--help' || word === '--version') {
      if (options[word]) fail('USAGE_ERROR', `Repeated option ${word}.`);
      options[word] = true;
    } else if (valueOptions.includes(word)) {
      if (options[word] !== undefined || !argv[i + 1] || argv[i + 1].startsWith('--')) fail('USAGE_ERROR', `Supply ${word} once with a value.`);
      options[word] = argv[++i];
    } else if (word.startsWith('-')) fail('USAGE_ERROR', `Unknown option ${word}. Use --help.`);
    else positional.push(word);
  }
  const [command = 'help', ...args] = positional;
  const allowed = {
    init: [], doctor: [], check: [], plan: [], render: ['--out'], status: ['--job'], variant: ['--out', '--patch'],
    captions: ['--words', '--out', '--group-size'], batch: ['--variants', '--out-dir'], inspect: ['--out-dir', '--scene-threshold'],
    reconstruct: ['--out-dir', '--scene-threshold'], transcribe: ['--out-dir', '--language'], resume: ['--job', '--out'], 'resume-batch': [],
    'reference-prepare': ['--inputs', '--brief', '--timings', '--out-dir', '--scene-threshold'], 'reference-check': [],
    'frameflow-check': ['--inputs', '--brief', '--timings'], 'frameflow-export': ['--concept', '--out-dir'],
    'reference-sample': ['--concept', '--seconds', '--out-dir'], help: [],
  };
  const required = {
    render: ['--out'], status: ['--job'], variant: ['--out', '--patch'], captions: ['--words', '--out'], batch: ['--variants', '--out-dir'],
    inspect: ['--out-dir'], reconstruct: ['--out-dir'], transcribe: ['--out-dir'], resume: ['--job'],
    'reference-prepare': ['--inputs', '--brief', '--out-dir'], 'frameflow-check': ['--inputs', '--brief'],
    'frameflow-export': ['--concept', '--out-dir'], 'reference-sample': ['--concept', '--seconds', '--out-dir'],
  };
  if (options['--help']) return { command: 'help', args: [], options };
  if (options['--version']) return { command: 'version', args: [], options };
  if (!Object.hasOwn(allowed, command)) fail('USAGE_ERROR', `Unknown command ${command}. Use --help.`);
  for (const key of valueOptions) {
    if (options[key] !== undefined && !allowed[command].includes(key)) fail('USAGE_ERROR', `${key} is not supported by ${command}.`);
  }
  const count = command === 'init' ? [0, 1] : ['doctor', 'help'].includes(command) ? [0, 0] : [1, 1];
  if (args.length < count[0] || args.length > count[1]) fail('USAGE_ERROR', `Wrong arguments for ${command}. Use --help.`);
  for (const key of required[command] ?? []) if (options[key] === undefined) fail('USAGE_ERROR', `${command} requires ${key}.`);
  return { command, args, options };
}

function plan(project) {
  let duration = 0;
  const clips = resolveClips(project).map((clip, index) => {
    const start = duration;
    duration += clip.duration;
    return { id: clip.id, kind: clip.kind, start, end: duration, ...(clip.src ? { src: clip.src } : {}), ...(project.clips[index].untilWord ? { untilWord: project.clips[index].untilWord } : {}) };
  });
  const overlays = resolveOverlays(project);
  return { title: project.title, duration, renderDuration: Math.round(duration * project.canvas.fps) / project.canvas.fps, ...project.canvas, clips, overlays, overlayCount: overlays.length, captionCount: project.captions.length, captions: resolveCaptions(project), wordCount: project.words.length, audioTrackCount: project.audio.length };
}

async function writeNew(file, data) {
  try { await writeFile(file, JSON.stringify(data, null, 2) + '\n', { flag: 'wx' }); }
  catch (error) {
    if (error.code === 'EEXIST') fail('OUTPUT_EXISTS', `File already exists; choose a new filename: ${file}`);
    throw error;
  }
}

async function readJson(file, code) {
  try {
    const info = await stat(file);
    if (!info.isFile()) fail(code, 'Input JSON must be a regular file.');
    if (info.size > 2 * 1024 * 1024) fail(code, 'Input JSON exceeds 2 MiB.');
    return JSON.parse(await readFile(file, 'utf8'));
  } catch (error) { fail(code, `Cannot read ${file}: ${error.message}`); }
}

async function saveSibling(loaded, project, destination) {
  const output = resolve(destination);
  if (await realpath(dirname(output)) !== loaded.root) fail('INVALID_VARIANT_PATH', 'Save the new project beside its source so media references keep their meaning.');
  await validateAssets(project, loaded.root);
  await writeNew(output, project);
  return { project: output, title: project.title, message: `Saved ${output}. Check its plan before rendering.` };
}

async function withCancellation(action) {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  process.once('SIGINT', cancel);
  process.once('SIGTERM', cancel);
  try { return await action(controller.signal); }
  finally { process.off('SIGINT', cancel); process.off('SIGTERM', cancel); }
}

async function newDirectory(destination) {
  const directory = resolve(destination);
  await mkdir(dirname(directory), { recursive: true });
  try { await mkdir(directory); }
  catch (error) {
    if (error.code === 'EEXIST') fail('OUTPUT_EXISTS', `Output directory already exists; choose a new directory: ${directory}`);
    throw error;
  }
  return directory;
}

async function projectRoot(path) {
  const canonical = await realpath(resolve(path));
  return (await stat(canonical)).isDirectory() ? canonical : dirname(canonical);
}

function checkBatchResult(batch) {
  if (batch.status !== 'succeeded') throw Object.assign(new Error(`Batch finished with status ${batch.status}. See ${resolve(batch.directory, 'batch.json')}.`), { code: batch.status === 'cancelled' ? 'CANCELLED' : 'BATCH_FAILED', batch });
  return { batch, message: `Completed ${batch.variants.length} cuts in ${batch.directory}` };
}

async function execute({ command, args, options }) {
  if (command === 'help') return { help };
  if (command === 'version') {
    const manifest = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
    return { version: manifest.version };
  }
  if (command === 'doctor') {
    const tools = await (await import('./render.mjs')).checkTools();
    const configured = Boolean(process.env.WHISPER_CPP_PATH && process.env.WHISPER_CPP_MODEL);
    const checks = configured ? await Promise.allSettled([stat(resolve(process.env.WHISPER_CPP_PATH)), stat(resolve(process.env.WHISPER_CPP_MODEL))]) : [];
    return { ...tools, transcription: { configured, filesPresent: configured && checks.every(result => result.status === 'fulfilled' && result.value.isFile()), configuration: 'WHISPER_CPP_PATH and WHISPER_CPP_MODEL select the local whisper.cpp executable and model; actual recognition is checked when transcribe runs.' } };
  }
  if (command === 'init') {
    const directory = resolve(args[0] ?? 'video-project');
    await mkdir(directory, { recursive: true });
    const project = validateProject(JSON.parse(await readFile(new URL('../examples/hello/project.json', import.meta.url), 'utf8')));
    const file = resolve(directory, 'project.json');
    await writeNew(file, project);
    await mkdir(resolve(directory, 'assets'), { recursive: true });
    return { project: file, message: `Created ${file}. Run check, then render with --out <new-video.mp4>.` };
  }
  if (command === 'status') {
    return { job: await readJob(await projectRoot(args[0]), options['--job']) };
  }
  if (command === 'inspect' || command === 'reconstruct') {
    const { inspectMedia, reconstructMedia } = await import('./media.mjs');
    const sceneThreshold = Number(options['--scene-threshold'] ?? 0.3);
    if (!Number.isFinite(sceneThreshold) || sceneThreshold < 0 || sceneThreshold > 1) fail('INVALID_ARGUMENT', 'Scene threshold must be from 0 through 1.');
    return withCancellation(async signal => {
      if (command === 'reconstruct') return reconstructMedia(args[0], options['--out-dir'], { sceneThreshold, signal });
      const workDir = await newDirectory(options['--out-dir']);
      return { inspection: await inspectMedia(args[0], { workDir, sceneThreshold, signal }) };
    });
  }
  if (command === 'transcribe') {
    const { transcribeMedia } = await import('./transcribe.mjs');
    return withCancellation(async signal => {
      const workDir = await newDirectory(options['--out-dir']);
      const transcript = await transcribeMedia(args[0], { workDir, language: options['--language'] ?? 'en', signal });
      const words = resolve(workDir, 'words.json');
      await writeNew(words, transcript.words);
      await writeNew(resolve(workDir, 'report.json'), { ...transcript, words });
      return { transcript: { ...transcript, wordCount: transcript.words.length, words }, message: `Recognized ${transcript.words.length} words. Saved ${words}` };
    });
  }
  if (command === 'resume') {
    const { resumeJob } = await import('./resume.mjs');
    const root = await projectRoot(args[0]);
    return withCancellation(async signal => {
      const job = await resumeJob(root, options['--job'], { output: options['--out'], signal, onProgress: progress => process.stderr.write(`[${progress.jobId}] ${progress.stage} ${progress.completed}/${progress.total}${progress.cached ? ' (reused)' : ''}\n`) });
      return { job, message: `Created ${job.output}\nJob ${job.id} resumed from ${options['--job']}` };
    });
  }
  if (command === 'resume-batch') {
    const { resumeBatch } = await import('./resume.mjs');
    return withCancellation(async signal => checkBatchResult(await resumeBatch(args[0], { signal, onProgress: progress => process.stderr.write(`[${progress.variantId}/${progress.jobId}] ${progress.stage} ${progress.completed}/${progress.total}${progress.cached ? ' (reused)' : ''}\n`) })));
  }
  if (command === 'frameflow-check') {
    const { validateBrief, validateInputs, validateStoryboard, checkFrameflowFiles } = await import('./frameflow.mjs');
    const baseDir = dirname(resolve(options['--inputs']));
    const inputs = validateInputs(await readJson(resolve(options['--inputs']), 'INVALID_FRAMEFLOW'), { baseDir });
    const brief = validateBrief(await readJson(resolve(options['--brief']), 'INVALID_FRAMEFLOW'));
    const timings = options['--timings'] ? await readJson(resolve(options['--timings']), 'INVALID_FRAMEFLOW') : {};
    const checked = validateStoryboard(await readJson(resolve(args[0]), 'INVALID_FRAMEFLOW'), { inputs, brief, timings, baseDir });
    return withCancellation(async signal => ({ ...checked, files: await checkFrameflowFiles(inputs, checked.storyboard, { signal, brief }) }));
  }
  if (['reference-prepare', 'reference-check', 'frameflow-export', 'reference-sample'].includes(command)) {
    const { prepareReference, checkReference, exportFrameflow, sampleReference } = await import('./reference.mjs');
    return withCancellation(async signal => {
      if (command === 'reference-prepare') return prepareReference(args[0], {
        inputsFile: options['--inputs'], briefFile: options['--brief'], timingsFile: options['--timings'],
        outDir: options['--out-dir'], sceneThreshold: Number(options['--scene-threshold'] ?? 0.3), signal,
      });
      if (command === 'reference-check') return checkReference(args[0], { signal });
      const request = { concept: options['--concept'], outDir: options['--out-dir'], signal };
      return command === 'frameflow-export' ? exportFrameflow(args[0], request)
        : sampleReference(args[0], { ...request, seconds: Number(options['--seconds']) });
    });
  }
  const loaded = await loadProject(args[0]);
  if (command === 'check' || command === 'plan') return plan(loaded.project);
  if (command === 'variant') {
    const patch = await readJson(resolve(options['--patch']), 'INVALID_PATCH');
    if (!patch || Array.isArray(patch) || typeof patch !== 'object') fail('INVALID_PATCH', 'Patch must be an object of project fields to replace.');
    const updated = validateProject({ ...loaded.project, ...patch });
    return saveSibling(loaded, updated, options['--out']);
  }
  if (command === 'captions') {
    const words = await readJson(resolve(options['--words']), 'INVALID_WORDS');
    if (!Array.isArray(words) || words.length === 0) fail('INVALID_WORDS', 'Supply a nonempty array of timed words.');
    const captions = groupWordCaptions(words, Number(options['--group-size'] ?? 4));
    const updated = validateProject({ ...loaded.project, words, captions });
    return saveSibling(loaded, updated, options['--out']);
  }
  if (command === 'batch') {
    const variants = await readJson(resolve(options['--variants']), 'INVALID_BATCH');
    return withCancellation(async signal => {
      const batch = await runBatch(loaded, variants, options['--out-dir'], {
        signal,
        onProgress: progress => process.stderr.write(`[${progress.variantId}/${progress.jobId}] ${progress.stage} ${progress.completed}/${progress.total}${progress.cached ? ' (reused)' : ''}\n`),
      });
      return checkBatchResult(batch);
    });
  }
  return withCancellation(async signal => {
    const job = await runJob(loaded, options['--out'], {
      signal,
      onProgress: progress => process.stderr.write(`[${progress.jobId}] ${progress.stage} ${progress.completed}/${progress.total}\n`),
    });
    return { job, message: `Created ${job.output}\nJob ${job.id}` };
  });
}

export async function runCli(argv) {
  const json = argv.includes('--json');
  try {
    const request = parse(argv);
    const result = await execute(request);
    if (json) process.stdout.write(JSON.stringify({ ok: true, command: request.command, ...result }) + '\n');
    else if (result.help) process.stdout.write(result.help);
    else if (result.version) process.stdout.write(result.version + '\n');
    else if (result.message) process.stdout.write(result.message + '\n');
    else process.stdout.write(JSON.stringify(result, null, 2) + '\n');
  } catch (error) {
    const result = { ok: false, error: { code: error.code ?? 'COMMAND_FAILED', message: error.message, ...(error.details ? { details: error.details } : {}) }, ...(error.jobId ? { jobId: error.jobId } : {}), ...(error.batch ? { batch: error.batch } : {}) };
    if (json) process.stdout.write(JSON.stringify(result) + '\n');
    else process.stderr.write(`${result.error.code}: ${result.error.message}${error.jobId ? `\nJob ${error.jobId}` : ''}\n`);
    process.exitCode = error.code === 'USAGE_ERROR' ? 2 : ['ABORT_ERR', 'CANCELLED'].includes(error.code) || error.name === 'AbortError' ? 130 : 1;
  }
}
