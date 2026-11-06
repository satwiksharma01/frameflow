import { createReadStream } from 'node:fs';
import { lstat, readFile, realpath } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { jobDirectory, readJob, runJob } from './jobs.mjs';
import { executeBatchUnlocked, prepareBatchProjects } from './batch.mjs';
import { withBatchLock } from './execution-lock.mjs';
import { validateAssets, validateProject } from './project.mjs';

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
const sha256 = /^[a-f0-9]{64}$/;
const maxSegmentBytes = 16 * 1024 ** 3;

function fail(code, message) { throw Object.assign(new Error(message), { code }); }
function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
function keys(value, allowed) { return object(value) && Object.keys(value).every(key => allowed.includes(key)); }
function identity(value, pattern) { return typeof value === 'string' && pattern.test(value); }
function inside(root, file) {
  const path = relative(root, file);
  return path !== '' && !isAbsolute(path) && path !== '..' && !path.startsWith(`..${sep}`);
}

async function digest(file, signal) {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(file, { signal })) hash.update(chunk);
  return hash.digest('hex');
}

async function ownedJson(directory, name, limit, code) {
  const root = await realpath(directory);
  const file = join(root, name);
  const info = await lstat(file);
  if (!info.isFile() || info.size > limit || !inside(root, await realpath(file))) fail(code, `${name} must be a regular file inside its state directory, within its size limit.`);
  try { return { value: JSON.parse(await readFile(file, 'utf8')), file, bytes: info.size }; }
  catch (error) { fail(code, `Cannot read ${name}: ${error.message}`); }
}

export async function loadSegmentCache(directory, { signal } = {}) {
  let metadata;
  try { metadata = await ownedJson(directory, 'segments.json', 64 * 1024, 'INVALID_SEGMENT_CACHE'); }
  catch (error) { if (error.code === 'ENOENT') return new Map(); throw error; }
  const { value } = metadata;
  if (!keys(value, ['version', 'segments']) || value.version !== 1 || !Array.isArray(value.segments) || value.segments.length > 100) fail('INVALID_SEGMENT_CACHE', 'Invalid segment cache metadata.');
  const root = await realpath(directory);
  const files = new Set();
  const cache = new Map();
  for (const entry of value.segments) {
    signal?.throwIfAborted();
    if (!keys(entry, ['key', 'file', 'sha256', 'bytes']) || !identity(entry.key, sha256) || !identity(entry.sha256, sha256)
      || typeof entry.file !== 'string' || !/^clip-(0|[1-9][0-9]?)\.mp4$/.test(entry.file) || files.has(entry.file)
      || !Number.isSafeInteger(entry.bytes) || entry.bytes < 1 || entry.bytes > maxSegmentBytes) fail('INVALID_SEGMENT_CACHE', 'Segment entries require unique generated filenames, bounded sizes, and SHA-256 identities.');
    files.add(entry.file);
    const file = join(root, entry.file);
    try {
      const info = await lstat(file);
      if (!info.isFile() || !inside(root, await realpath(file))) fail('INVALID_SEGMENT_CACHE', `Segment ${entry.file} must be a real file inside its job directory.`);
      if (info.size !== entry.bytes || await digest(file, signal) !== entry.sha256) continue;
      cache.set(entry.key, { file, sha256: entry.sha256 });
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  return cache;
}

async function originalRoot(record, expectedRoot) {
  if (typeof record.project !== 'string' || !isAbsolute(record.project) || record.project.includes('\0')) fail('INVALID_RESUME_RECORD', 'The original project location is missing or invalid.');
  const root = await realpath(dirname(record.project));
  if (record.assetRoot !== undefined && (typeof record.assetRoot !== 'string' || !isAbsolute(record.assetRoot) || await realpath(record.assetRoot) !== root)) fail('INVALID_RESUME_RECORD', 'The stored asset root differs from the original project directory.');
  if (expectedRoot && root !== await realpath(expectedRoot)) fail('INVALID_RESUME_RECORD', 'The job belongs to another project directory.');
  return root;
}

export async function resumeJob(root, id, options = {}) {
  const previous = await readJob(root, id);
  if (!['failed', 'cancelled', 'running'].includes(previous.status)) fail('JOB_NOT_RESUMABLE', 'Only failed, cancelled, or interrupted jobs can be resumed.');
  const assetRoot = await originalRoot(previous, root);
  const directory = await jobDirectory(assetRoot, id);
  const { value } = await ownedJson(directory, 'project.json', 2 * 1024 * 1024, 'INVALID_RESUME_RECORD');
  const project = validateProject(value);
  await validateAssets(project, assetRoot);
  const output = options.output ?? previous.output;
  if (typeof output !== 'string' || !output || (options.output === undefined && !isAbsolute(output))) fail('INVALID_RESUME_RECORD', 'The original output location is missing or invalid.');
  const clipCache = await loadSegmentCache(directory, { signal: options.signal });
  return runJob({ project, projectPath: previous.project, root: assetRoot }, output, { ...options, clipCache, resumedFrom: id });
}

function validateBatchRecord(batch, directory) {
  if (!object(batch) || batch.version !== 1 || !identity(batch.id, uuid) || batch.directory !== directory
    || !['running', 'succeeded', 'partial', 'failed', 'cancelled'].includes(batch.status)
    || !Array.isArray(batch.variants) || batch.variants.length < 1 || batch.variants.length > 100
    || !keys(batch.baseProject, ['file', 'bytes', 'sha256']) || batch.baseProject.file !== 'project.json'
    || !identity(batch.baseProject.sha256, sha256) || !Number.isSafeInteger(batch.baseProject.bytes)
    || batch.baseProject.bytes < 1 || batch.baseProject.bytes > 2 * 1024 * 1024) fail('INVALID_BATCH_RECORD', 'This batch has no valid immutable base snapshot or resume metadata.');
  for (const entry of batch.variants) {
    if (!object(entry) || !['pending', 'running', 'succeeded', 'failed', 'cancelled'].includes(entry.status)
      || (entry.jobId !== undefined && !identity(entry.jobId, uuid))
      || (entry.previousJobIds !== undefined && (!Array.isArray(entry.previousJobIds) || entry.previousJobIds.length > 1000 || entry.previousJobIds.some(id => !identity(id, uuid))))) fail('INVALID_BATCH_RECORD', 'The batch contains invalid variant state or job lineage.');
  }
}

async function verifyOutput(directory, entry, signal) {
  const expected = join(directory, `${entry.id}.mp4`);
  if (entry.output !== expected || !object(entry.artifact) || !identity(entry.artifact.sha256, sha256)
    || !Number.isSafeInteger(entry.artifact.bytes) || entry.artifact.bytes < 1 || entry.artifact.bytes > maxSegmentBytes) fail('BATCH_ARTIFACT_INVALID', `Completed variant ${entry.id} has invalid output metadata.`);
  try {
    const info = await lstat(expected);
    if (!info.isFile() || !inside(directory, await realpath(expected)) || info.size !== entry.artifact.bytes || await digest(expected, signal) !== entry.artifact.sha256) throw new Error('content does not match its saved digest');
  } catch (error) {
    if (signal?.aborted) throw error;
    fail('BATCH_ARTIFACT_INVALID', `Completed variant ${entry.id} is missing or corrupt; its output was preserved: ${error.message}`);
  }
}

export async function resumeBatch(path, options = {}) {
  const directory = await realpath(resolve(path));
  return withBatchLock(directory, () => resumeBatchUnlocked(directory, options));
}

async function resumeBatchUnlocked(directory, options) {
  const { value: batch } = await ownedJson(directory, 'batch.json', 8 * 1024 * 1024, 'INVALID_BATCH_RECORD');
  validateBatchRecord(batch, directory);
  const root = await originalRoot(batch);
  const snapshot = await ownedJson(directory, 'project.json', 2 * 1024 * 1024, 'INVALID_BATCH_RECORD');
  if (snapshot.bytes !== batch.baseProject.bytes || await digest(snapshot.file, options.signal) !== batch.baseProject.sha256) fail('INVALID_BATCH_RECORD', 'The batch base project snapshot has changed.');
  const loaded = { project: validateProject(snapshot.value), projectPath: batch.project, root };
  const projects = await prepareBatchProjects(loaded, batch.variants.map(({ id, patch }) => ({ id, patch })), options);
  for (const entry of batch.variants) if (entry.status === 'succeeded') await verifyOutput(directory, entry, options.signal);
  if (batch.variants.every(entry => entry.status === 'succeeded')) return batch;
  const clipCache = new Map();
  for (const entry of batch.variants) {
    for (const id of [...(entry.previousJobIds ?? []), ...(entry.jobId ? [entry.jobId] : [])]) {
      let previousDirectory;
      try { previousDirectory = await jobDirectory(root, id); }
      catch (error) { if (error.code === 'ENOENT') continue; throw error; }
      for (const [key, value] of await loadSegmentCache(previousDirectory, { signal: options.signal })) clipCache.set(key, value);
    }
  }
  batch.resumeCount = (Number.isSafeInteger(batch.resumeCount) && batch.resumeCount >= 0 ? batch.resumeCount : 0) + 1;
  batch.resumedAt = new Date().toISOString();
  return executeBatchUnlocked(loaded, projects, batch, { ...options, clipCache });
}
