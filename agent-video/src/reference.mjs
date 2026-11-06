import { lstat, mkdir, readFile, realpath, stat, writeFile } from 'node:fs/promises';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { inspectMedia } from './media.mjs';
import { fileDigest, sourceMetadata } from './media-process.mjs';
import { checkFrameflowFiles, validateBrief, validateInputs, validateStoryboard, validateTimings } from './frameflow.mjs';
import { analyzeReference, referenceRequest, validateReferenceAnalysis } from './reference-evidence.mjs';

const maxJsonBytes = 2 * 1024 * 1024;
const hexDigest = /^[a-f0-9]{64}$/;
const identifier = /^[A-Za-z][A-Za-z0-9_-]{0,63}$/;
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value)
  && [Object.prototype, null].includes(Object.getPrototypeOf(value));
const onlyKeys = (value, keys) => object(value) && Object.keys(value).every(key => keys.includes(key));
const inside = (root, file) => {
  const part = relative(root, file);
  return part !== '' && !isAbsolute(part) && part !== '..' && !part.startsWith(`..${sep}`);
};
function fail(code, message) { throw Object.assign(new Error(message), { code }); }
function cancelled(signal) { if (signal?.aborted) fail('CANCELLED', 'Reference preparation was cancelled.'); }
function requiredText(value, name, max = 4000) {
  if (typeof value !== 'string' || !value.trim() || value.length > max || value.includes('\0')) {
    fail('INVALID_CONCEPTS', `${name} must be nonempty text of at most ${max} characters without NUL bytes.`);
  }
  return value;
}

export async function readReferenceJson(file, { root, signal } = {}) {
  cancelled(signal);
  try {
    if (typeof file !== 'string' || !file.trim()) throw new Error('expected a JSON file path');
    const path = resolve(file);
    const info = await lstat(path);
    if (!info.isFile() || info.size > maxJsonBytes) throw new Error('expected a regular JSON file of at most 2 MiB');
    const canonical = await realpath(path);
    if (root && !inside(await realpath(root), canonical)) throw new Error('document leaves its session directory');
    return JSON.parse(await readFile(canonical, { encoding: 'utf8', signal }));
  } catch (error) {
    cancelled(signal);
    fail('REFERENCE_READ_FAILED', `Cannot read reference document ${String(file)}: ${error.message}`);
  }
}

async function hashFile(file, signal) {
  cancelled(signal);
  const path = await realpath(file);
  const info = await stat(path);
  if (!info.isFile()) fail('INVALID_REFERENCE_SESSION', `Expected a regular source file: ${path}`);
  try { return { path, bytes: info.size, sha256: await fileDigest(path, signal) }; }
  catch (error) { cancelled(signal); throw error; }
}

function inventoryPaths(inputs) {
  return [...inputs.footage.map(item => item.source), ...inputs.assets.map(item => item.path), ...inputs.music.map(item => item.path)];
}

async function hashInventory(inputs, signal) {
  const files = new Map();
  for (const path of inventoryPaths(inputs)) {
    const canonical = await realpath(path);
    if (!files.has(canonical)) files.set(canonical, await hashFile(canonical, signal));
  }
  return [...files.values()];
}

async function newDirectory(outDir, signal) {
  cancelled(signal);
  if (typeof outDir !== 'string' || !outDir.trim()) fail('INVALID_ARGUMENT', 'A new output directory is required.');
  const path = resolve(outDir);
  await mkdir(dirname(path), { recursive: true });
  try { await mkdir(path); }
  catch (error) {
    if (error.code === 'EEXIST') fail('OUTPUT_EXISTS', `Output directory already exists; choose a new directory: ${path}`);
    throw error;
  }
  return realpath(path);
}

async function writeJson(path, value, signal) {
  cancelled(signal);
  const content = JSON.stringify(value, null, 2) + '\n';
  if (Buffer.byteLength(content) > maxJsonBytes) fail('INVALID_REFERENCE_SESSION', 'A reference document exceeds the 2 MiB limit.');
  await writeFile(path, content, { flag: 'wx', signal });
}

function validPin(value) {
  return onlyKeys(value, ['path', 'sha256', 'bytes']) && typeof value.path === 'string' && isAbsolute(value.path)
    && !value.path.includes('\0') && typeof value.sha256 === 'string' && hexDigest.test(value.sha256)
    && Number.isSafeInteger(value.bytes) && value.bytes > 0;
}

async function verifyPin(pin, signal) {
  if (!validPin(pin)) fail('INVALID_REFERENCE_SESSION', 'Source provenance requires a path, byte count, and SHA-256 digest.');
  try {
    const current = await hashFile(pin.path, signal);
    if (current.path !== pin.path || current.bytes !== pin.bytes || current.sha256 !== pin.sha256) throw new Error('content or canonical path changed');
  } catch (error) {
    cancelled(signal);
    fail('SOURCE_CHANGED', `Prepared source changed or is unavailable: ${pin.path}: ${error.message}`);
  }
}

async function evidencePins(directory, evidence, signal) {
  const paths = [join(directory, 'inspection', 'report.json'), join(directory, 'inspection', 'metadata.json'), ...evidence.frames,
    ...(evidence.contactSheet ? [evidence.contactSheet] : [])];
  const pins = [];
  for (const path of new Set(paths)) {
    const canonical = await realpath(path);
    if (!inside(directory, canonical) || !(await lstat(path)).isFile()) fail('INVALID_REFERENCE_SESSION', 'Reference evidence must be regular files inside its session.');
    pins.push(await hashFile(canonical, signal));
  }
  return pins;
}

export async function prepareReference(referenceFile, { inputsFile, briefFile, timingsFile, outDir, sceneThreshold = 0.3, signal } = {}) {
  cancelled(signal);
  if (typeof sceneThreshold !== 'number' || !Number.isFinite(sceneThreshold) || sceneThreshold < 0 || sceneThreshold > 1) {
    fail('INVALID_ARGUMENT', 'sceneThreshold must be a finite number from zero through one.');
  }
  const rawInputs = await readReferenceJson(inputsFile, { signal });
  const brief = validateBrief(await readReferenceJson(briefFile, { signal }));
  const baseDir = await realpath(dirname(resolve(inputsFile)));
  const inputs = validateInputs(rawInputs, { baseDir });
  const timings = validateTimings(timingsFile === undefined ? {} : await readReferenceJson(timingsFile, { signal }), inputs);
  await checkFrameflowFiles(inputs, undefined, { signal });
  const source = await sourceMetadata(referenceFile, signal);
  if (!source.video) fail('INVALID_MEDIA', 'Reference preparation requires a video picture stream.');
  const files = await hashInventory(inputs, signal);
  const directory = await newDirectory(outDir, signal);
  const inspection = join(directory, 'inspection');
  await mkdir(inspection);
  const report = await inspectMedia(source.source, { workDir: inspection, sceneThreshold, signal, focusOpening: true });
  const evidence = analyzeReference(report);
  const reference = await hashFile(source.source, signal);
  if (reference.sha256 !== report.sha256) fail('SOURCE_CHANGED', 'The reference changed during inspection; prepare a fresh session.');
  const warnings = files.some(file => file.path === reference.path || file.sha256 === reference.sha256)
    ? ['The supplied inventory explicitly reuses the reference; concepts must disclose that reuse.'] : [];
  const session = { version: 1, baseDir, inputs, brief, timings, evidence,
    provenance: { reference, files, evidenceFiles: await evidencePins(directory, evidence, signal) } };
  const sessionFile = join(directory, 'session.json');
  const request = join(directory, 'analysis-request.md');
  await writeJson(sessionFile, session, signal);
  await writeFile(request, referenceRequest(session), { flag: 'wx', signal });
  return { directory, session: sessionFile, request, evidence, warnings };
}

function validateSession(value) {
  if (!onlyKeys(value, ['version', 'baseDir', 'inputs', 'brief', 'timings', 'evidence', 'provenance']) || value.version !== 1
      || typeof value.baseDir !== 'string' || !isAbsolute(value.baseDir) || value.baseDir.includes('\0')
      || !onlyKeys(value.provenance, ['reference', 'files', 'evidenceFiles']) || !validPin(value.provenance.reference)
      || !Array.isArray(value.provenance.files) || value.provenance.files.length > 2048
      || !Array.isArray(value.provenance.evidenceFiles) || value.provenance.evidenceFiles.length < 2 || value.provenance.evidenceFiles.length > 16
      || !value.provenance.files.every(validPin) || !value.provenance.evidenceFiles.every(validPin)) {
    fail('INVALID_REFERENCE_SESSION', 'Expected a version-1 reference session with normalized context and bounded source/evidence provenance.');
  }
}

async function checkPins(session, directory, inputs, signal) {
  await verifyPin(session.provenance.reference, signal);
  const actualPaths = new Set();
  for (const path of inventoryPaths(inputs)) {
    try { actualPaths.add(await realpath(path)); }
    catch (error) { fail('SOURCE_CHANGED', `Prepared supplied media is missing: ${path}: ${error.message}`); }
  }
  if (actualPaths.size !== session.provenance.files.length || new Set(session.provenance.files.map(file => file.path)).size !== actualPaths.size
      || session.provenance.files.some(file => !actualPaths.has(file.path))) fail('SOURCE_CHANGED', 'The prepared supplied-media paths changed.');
  for (const pin of session.provenance.files) await verifyPin(pin, signal);
  const expectedReport = join(directory, 'inspection', 'report.json');
  if (!session.provenance.evidenceFiles.some(pin => pin.path === expectedReport)) fail('INVALID_REFERENCE_SESSION', 'The inspection report is missing from evidence provenance.');
  for (const pin of session.provenance.evidenceFiles) {
    if (!inside(directory, pin.path)) fail('INVALID_REFERENCE_SESSION', 'Evidence provenance leaves the session directory.');
    await verifyPin(pin, signal);
    if (!(await lstat(pin.path)).isFile()) fail('INVALID_REFERENCE_SESSION', 'Evidence cannot be a symlink.');
  }
}

async function conceptsFor(value, session, signal) {
  if (!onlyKeys(value, ['version', 'concepts']) || value.version !== 1 || !Array.isArray(value.concepts)
      || value.concepts.length < 2 || value.concepts.length > 3) {
    fail('INVALID_CONCEPTS', 'concepts.json must contain version 1 and exactly two or three concept proposals.');
  }
  const ids = new Set();
  const concepts = [];
  for (const [index, raw] of value.concepts.entries()) {
    cancelled(signal);
    if (!onlyKeys(raw, ['id', 'title', 'summary', 'adaptation', 'storyboard']) || typeof raw.id !== 'string' || !identifier.test(raw.id)
        || ids.has(raw.id.toLowerCase())) fail('INVALID_CONCEPTS', `Concept ${index} needs a unique safe ID and only id/title/summary/adaptation/storyboard fields.`);
    ids.add(raw.id.toLowerCase());
    const concept = { id: raw.id, title: requiredText(raw.title, 'Concept title', 200), summary: requiredText(raw.summary, 'Concept summary'), adaptation: requiredText(raw.adaptation, 'Concept adaptation') };
    const result = validateStoryboard(raw.storyboard, { inputs: session.inputs, brief: session.brief, timings: session.timings, baseDir: session.baseDir });
    await checkFrameflowFiles(session.inputs, result.storyboard, { signal, brief: session.brief });
    concepts.push({ ...concept, ...result });
  }
  return concepts;
}

export async function checkReference(sessionDir, { signal } = {}) {
  cancelled(signal);
  const directory = await realpath(resolve(sessionDir));
  const stored = await readReferenceJson(join(directory, 'session.json'), { root: directory, signal });
  validateSession(stored);
  const brief = validateBrief(stored.brief);
  const inputs = validateInputs(stored.inputs, { baseDir: stored.baseDir });
  const timings = validateTimings(stored.timings, inputs);
  const session = { ...stored, inputs, brief, timings };
  await checkPins(session, directory, inputs, signal);
  const report = await readReferenceJson(join(directory, 'inspection', 'report.json'), { root: directory, signal });
  const evidence = analyzeReference(report);
  if (!isDeepStrictEqual(evidence, session.evidence) || evidence.source.path !== session.provenance.reference.path
      || evidence.source.sha256 !== session.provenance.reference.sha256) fail('INVALID_REFERENCE_SESSION', 'Stored reference evidence differs from its inspected report or source provenance.');
  const analysis = validateReferenceAnalysis(await readReferenceJson(join(directory, 'analysis.json'), { root: directory, signal }), evidence);
  const concepts = await conceptsFor(await readReferenceJson(join(directory, 'concepts.json'), { root: directory, signal }), session, signal);
  const warnings = [...new Set(concepts.flatMap(concept => concept.warnings))];
  if (session.provenance.files.some(file => file.sha256 === session.provenance.reference.sha256)) warnings.push('The supplied inventory explicitly reuses the reference; concepts must disclose that reuse.');
  return { directory, session, analysis, concepts, files: session.provenance.files, warnings };
}

function selectConcept(checked, id) {
  if (typeof id !== 'string' || !identifier.test(id)) fail('INVALID_ARGUMENT', 'Select a concept ID from the checked session.');
  const concept = checked.concepts.find(item => item.id === id);
  if (!concept) fail('CONCEPT_NOT_FOUND', `Concept ${id} was not found in this session.`);
  return concept;
}

export function verifyHandoffSource(pin, prepared, kind) {
  if ((!prepared && kind !== 'composition') || (prepared &&
    (prepared.path !== pin.path || prepared.bytes !== pin.bytes || prepared.sha256 !== pin.sha256))) {
    fail('SOURCE_CHANGED', `Prepared supplied media changed while validating the handoff: ${pin.path}`);
  }
}

async function handoff(checked, concept, outDir, { signal, sample } = {}) {
  const { session } = checked;
  await verifyPin(session.provenance.reference, signal);
  const checkedFiles = await checkFrameflowFiles(session.inputs, concept.storyboard, { signal, brief: session.brief });
  const files = new Map(session.provenance.files.map(file => [file.path, file]));
  const warnings = [...concept.warnings];
  if (session.provenance.files.some(file => file.sha256 === session.provenance.reference.sha256)) {
    warnings.push('The supplied inventory explicitly reuses the reference; concepts must disclose that reuse.');
  }
  if (checkedFiles.files.some(file => file.kind === 'composition')) {
    warnings.push('HTML composition provenance covers its index.html entry point only. Frameflow must inspect dependent files and review execution before building.');
  }
  if (sample && sample.retainedScenes < sample.originalScenes) {
    warnings.push('The sample retains only initial scenes; its script remains the full concept text for review context.');
  }
  for (const file of checkedFiles.files) {
    const info = await stat(file.path);
    const path = info.isDirectory() ? join(file.path, 'index.html') : file.path;
    const pin = await hashFile(path, signal);
    const prepared = files.get(pin.path);
    verifyHandoffSource(pin, prepared, file.kind);
    files.set(pin.path, pin);
  }
  const directory = await newDirectory(outDir, signal);
  const documents = {
    'storyboard.json': concept.storyboard,
    'brief.json': session.brief,
    'inputs.json': session.inputs,
    'source-timings.json': session.timings,
    'reference-analysis.json': { version: 1, evidence: session.evidence, analysis: checked.analysis },
  };
  const hashes = [];
  for (const [name, value] of Object.entries(documents)) {
    await writeJson(join(directory, name), value, signal);
    const pin = await hashFile(join(directory, name), signal);
    hashes.push({ file: name, sha256: pin.sha256, bytes: pin.bytes });
  }
  const manifest = {
    version: 1, kind: sample ? 'frameflow-sample' : 'frameflow-handoff',
    concept: { id: concept.id, title: concept.title, summary: concept.summary, adaptation: concept.adaptation },
    duration: concept.duration, timeline: concept.timeline,
    timelineAuthority: 'proposal; Frameflow must resolve delegated timing before its native build',
    requirements: concept.requirements, warnings: [...new Set(warnings)],
    approvals: { concept: 'pending', storyboard: 'pending', frameflowBuild: 'pending' },
    reference: session.provenance.reference, sources: [...files.values()], evidenceFiles: session.provenance.evidenceFiles, documents: hashes,
    ...(sample ? { sample } : {}),
    createdAt: new Date().toISOString(),
  };
  await writeJson(join(directory, 'manifest.json'), manifest, signal);
  return { directory, storyboard: join(directory, 'storyboard.json'), brief: join(directory, 'brief.json'), inputs: join(directory, 'inputs.json'),
    timings: join(directory, 'source-timings.json'), analysis: join(directory, 'reference-analysis.json'), manifest: join(directory, 'manifest.json') };
}

export async function exportFrameflow(sessionDir, { concept, outDir, signal } = {}) {
  const checked = await checkReference(sessionDir, { signal });
  return handoff(checked, selectConcept(checked, concept), outDir, { signal });
}

export async function sampleReference(sessionDir, { concept, seconds, outDir, signal } = {}) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds <= 0 || seconds > 86400) fail('INVALID_ARGUMENT', 'Sample seconds must be a finite maximum greater than zero and at most 86400.');
  const checked = await checkReference(sessionDir, { signal });
  const selected = selectConcept(checked, concept);
  let count = 0;
  for (const scene of selected.timeline) {
    if (scene.end > seconds + 1e-9) break;
    count += 1;
  }
  if (count === 0) fail('SAMPLE_TOO_SHORT', 'The first complete scene exceeds this sample maximum; choose a longer sample or author a safely cut scene.');
  const storyboard = { ...selected.storyboard, scenes: selected.storyboard.scenes.slice(0, count) };
  const result = validateStoryboard(storyboard, { inputs: checked.session.inputs, brief: checked.session.brief, timings: checked.session.timings, baseDir: checked.session.baseDir });
  return handoff(checked, { ...selected, ...result }, outDir, { signal, sample: { maximumSeconds: seconds, originalScenes: selected.storyboard.scenes.length, retainedScenes: count } });
}
