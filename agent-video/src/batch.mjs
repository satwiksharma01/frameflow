import { mkdir, realpath, rename, writeFile } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import { dirname, join, resolve } from 'node:path';
import { validateAssets, validateProject } from './project.mjs';
import { runJob } from './jobs.mjs';
import { withBatchLock } from './execution-lock.mjs';

function fail(message) { throw Object.assign(new Error(message), { code: 'INVALID_BATCH' }); }
function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }

export async function saveBatch(directory, batch) {
  const temporary = join(directory, `batch.json.${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(batch, null, 2) + '\n', { flag: 'wx' });
  await rename(temporary, join(directory, 'batch.json'));
}

export async function prepareBatchProjects(loaded, variants, options = {}) {
  if (!Array.isArray(variants) || variants.length < 1 || variants.length > 100) fail('Variants must be an array with 1 through 100 entries.');
  const ids = new Set();
  const projects = [];
  for (const [index, variant] of variants.entries()) {
    if (!object(variant) || Object.keys(variant).some(key => !['id', 'patch'].includes(key))) fail(`Variant ${index} must have only id and patch.`);
    if (typeof variant.id !== 'string' || !/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(variant.id)
        || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i.test(variant.id)) fail(`Variant ${index} has an unsafe output ID.`);
    if (ids.has(variant.id.toLowerCase())) fail(`Duplicate output ID ${variant.id}. IDs are case-insensitive.`);
    ids.add(variant.id.toLowerCase());
    if (!object(variant.patch)) fail(`Variant ${variant.id} patch must be an object.`);
    options.signal?.throwIfAborted();
    const project = validateProject({ ...loaded.project, ...variant.patch });
    await validateAssets(project, loaded.root);
    projects.push(project);
  }

  return projects;
}

export async function runBatch(loaded, variants, outDir, options = {}) {
  const base = validateProject(loaded.project);
  const projects = await prepareBatchProjects({ ...loaded, project: base }, variants, options);
  const output = resolve(outDir);
  await mkdir(dirname(output), { recursive: true });
  try { await mkdir(output); }
  catch (error) {
    if (error.code === 'EEXIST') throw Object.assign(new Error(`Batch output directory already exists; choose a new directory: ${output}`), { code: 'OUTPUT_EXISTS' });
    throw error;
  }
  const directory = await realpath(output);
  const source = JSON.stringify(base, null, 2) + '\n';
  await writeFile(join(directory, 'project.json'), source, { flag: 'wx' });
  const batch = {
    version: 1, id: randomUUID(), status: 'running', project: resolve(loaded.projectPath), assetRoot: await realpath(loaded.root), directory,
    baseProject: { file: 'project.json', sha256: createHash('sha256').update(source).digest('hex'), bytes: Buffer.byteLength(source) },
    startedAt: new Date().toISOString(),
    variants: variants.map(variant => ({ id: variant.id, patch: variant.patch, status: 'pending' })),
  };
  return executeBatch(loaded, projects, batch, options);
}

export async function executeBatch(loaded, projects, batch, options = {}) {
  return withBatchLock(batch.directory, () => executeBatchUnlocked(loaded, projects, batch, options));
}

export async function executeBatchUnlocked(loaded, projects, batch, options = {}) {
  const directory = batch.directory;
  batch.status = 'running';
  delete batch.finishedAt;
  await saveBatch(directory, batch);
  const clipCache = options.clipCache ?? new Map();
  for (const [index, entry] of batch.variants.entries()) {
    if (entry.status === 'succeeded') continue;
    if (options.signal?.aborted) {
      for (const pending of batch.variants.slice(index)) if (pending.status !== 'succeeded') pending.status = 'cancelled';
      break;
    }
    const previousJob = entry.jobId ?? entry.previousJobIds?.at(-1);
    if (entry.jobId) entry.previousJobIds = [...(entry.previousJobIds ?? []), entry.jobId];
    delete entry.jobId;
    delete entry.error;
    delete entry.output;
    delete entry.artifact;
    entry.status = 'running';
    await saveBatch(directory, batch);
    try {
      const job = await runJob({ ...loaded, project: projects[index] }, join(directory, `${entry.id}.mp4`), {
        render: options.render, signal: options.signal, clipCache, resumedFrom: previousJob,
        async onProgress(progress) {
          if (entry.jobId !== progress.jobId) {
            entry.jobId = progress.jobId;
            await saveBatch(directory, batch);
          }
          await options.onProgress?.({ variantId: entry.id, ...progress });
        },
      });
      entry.status = 'succeeded';
      entry.jobId = job.id;
      entry.output = job.output;
      entry.artifact = job.artifact;
    } catch (error) {
      entry.status = options.signal?.aborted ? 'cancelled' : 'failed';
      entry.error = { code: entry.status === 'cancelled' ? 'CANCELLED' : (error.code ?? 'RENDER_FAILED'), message: error.message };
      if (error.jobId) entry.jobId = error.jobId;
    }
    await saveBatch(directory, batch);
  }
  const successes = batch.variants.filter(entry => entry.status === 'succeeded').length;
  batch.status = options.signal?.aborted ? 'cancelled' : successes === batch.variants.length ? 'succeeded' : successes > 0 ? 'partial' : 'failed';
  batch.finishedAt = new Date().toISOString();
  await saveBatch(directory, batch);
  return batch;
}
