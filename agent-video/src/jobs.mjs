import { constants, createReadStream } from 'node:fs';
import { copyFile, lstat, mkdir, readFile, realpath, rename, stat, writeFile } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import { dirname, extname, isAbsolute, join, relative, resolve } from 'node:path';
import { validateAssets, validateProject } from './project.mjs';

function failure(code, message) {
  return Object.assign(new Error(message), { code });
}

function inside(root, file) {
  const path = relative(root, file);
  return path !== '' && !isAbsolute(path) && path !== '..' && !path.startsWith(`..${process.platform === 'win32' ? '\\' : '/'}`);
}

async function jobStorage(root, create = false) {
  const canonicalRoot = await realpath(root);
  const home = join(canonicalRoot, '.agent-video');
  if (create) await mkdir(home, { recursive: true });
  if (!inside(canonicalRoot, await realpath(home))) throw failure('INVALID_JOB_STORAGE', 'Job storage must remain inside the project directory.');
  const directory = join(home, 'jobs');
  if (create) await mkdir(directory, { recursive: true });
  const canonical = await realpath(directory);
  if (!inside(canonicalRoot, canonical)) throw failure('INVALID_JOB_STORAGE', 'Job storage must remain inside the project directory.');
  return canonical;
}

async function saveJob(directory, job) {
  const temporary = join(directory, `job.json.${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(job, null, 2) + '\n', { flag: 'wx' });
  await rename(temporary, join(directory, 'job.json'));
}

export async function jobDirectory(root, id) {
  if (typeof id !== 'string' || !/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(id)) {
    throw failure('INVALID_JOB_ID', 'Use the job UUID printed by render.');
  }
  const storage = await jobStorage(root);
  const selected = join(storage, id);
  if (!(await lstat(selected)).isDirectory()) throw failure('INVALID_JOB_STORAGE', 'The selected job must be a real directory.');
  const directory = await realpath(selected);
  if (!inside(storage, directory)) throw failure('INVALID_JOB_STORAGE', 'The selected job leaves project storage.');
  return directory;
}

export async function readJob(root, id) {
  try {
    const directory = await jobDirectory(root, id);
    const file = join(directory, 'job.json');
    const info = await lstat(file);
    if (!info.isFile() || info.size > 128 * 1024) throw failure('INVALID_JOB_RECORD', 'The job record must be a regular JSON file of at most 128 KiB.');
    let job;
    try { job = JSON.parse(await readFile(file, 'utf8')); }
    catch { throw failure('INVALID_JOB_RECORD', `Job ${id} has invalid JSON.`); }
    if (!job || typeof job !== 'object' || job.id !== id || !['running', 'succeeded', 'failed', 'cancelled'].includes(job.status)) {
      throw failure('INVALID_JOB_RECORD', `Job ${id} has an invalid record.`);
    }
    return job;
  } catch (error) {
    if (error.code === 'ENOENT') throw failure('JOB_NOT_FOUND', `Job ${id} was not found in this project.`);
    throw error;
  }
}

export async function runJob(loaded, outputFile, options = {}) {
  options.signal?.throwIfAborted();
  const output = resolve(outputFile);
  if (extname(output).toLowerCase() !== '.mp4') throw failure('INVALID_OUTPUT', 'Output must have the .mp4 extension.');
  try {
    await lstat(output);
    throw failure('OUTPUT_EXISTS', `Output already exists; choose a new filename: ${output}`);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }

  const project = validateProject(loaded.project);
  const assetRoot = await realpath(loaded.root);
  await validateAssets(project, assetRoot);
  const storage = await jobStorage(assetRoot, true);
  const id = randomUUID();
  const directory = join(storage, id);
  await mkdir(directory);
  const job = { id, status: 'running', title: project.title, project: resolve(loaded.projectPath), assetRoot, output, ...(options.resumedFrom ? { resumedFrom: options.resumedFrom } : {}), startedAt: new Date().toISOString(), progress: { stage: 'starting', completed: 0, total: 1 } };
  await writeFile(join(directory, 'project.json'), JSON.stringify(project, null, 2) + '\n', { flag: 'wx' });
  await saveJob(directory, job);
  let progressWrites = Promise.resolve();
  const onProgress = progress => {
    progressWrites = progressWrites.then(async () => {
      await options.onProgress?.({ jobId: id, ...progress });
      job.progress = progress;
      await saveJob(directory, job);
    });
    return progressWrites;
  };

  try {
    await onProgress(job.progress);
    const render = options.render ?? (await import('./render.mjs')).renderVideo;
    const rendered = await render({ ...loaded, project, root: assetRoot }, { workDir: directory, onProgress, signal: options.signal, clipCache: options.clipCache });
    await progressWrites;
    options.signal?.throwIfAborted();
    const source = await realpath(rendered.file);
    if (!inside(await realpath(directory), source) || !(await stat(source)).isFile()) {
      throw failure('INVALID_RENDER_RESULT', 'The renderer did not return a file in its job directory.');
    }
    await mkdir(dirname(output), { recursive: true });
    try { await copyFile(source, output, constants.COPYFILE_EXCL); }
    catch (error) {
      if (error.code === 'EEXIST') throw failure('OUTPUT_EXISTS', `Output appeared during rendering; preserved it: ${output}`);
      throw error;
    }
    const hash = createHash('sha256');
    for await (const chunk of createReadStream(output)) hash.update(chunk);
    job.artifact = { bytes: (await stat(output)).size, sha256: hash.digest('hex'), duration: rendered.duration, width: rendered.width, height: rendered.height, fps: rendered.fps, ...(rendered.cache ? { cache: rendered.cache } : {}) };
    job.status = 'succeeded';
    job.progress = { stage: 'complete', completed: 1, total: 1 };
    job.finishedAt = new Date().toISOString();
    await saveJob(directory, job);
    return job;
  } catch (error) {
    await progressWrites.catch(() => {});
    job.status = options.signal?.aborted ? 'cancelled' : 'failed';
    job.error = { code: job.status === 'cancelled' ? 'CANCELLED' : (error.code ?? 'RENDER_FAILED'), message: error.message };
    job.finishedAt = new Date().toISOString();
    await saveJob(directory, job);
    error.jobId = id;
    throw error;
  }
}
