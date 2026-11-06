import { constants } from 'node:fs';
import { access, readFile, realpath, stat } from 'node:fs/promises';
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path';

export class ProjectError extends Error {
  constructor(code, message, details) {
    super(message);
    this.name = 'ProjectError';
    this.code = code;
    if (details !== undefined) this.details = details;
  }
}

function fail(path, reason) {
  throw new ProjectError('INVALID_PROJECT', `${path}: ${reason}`, { path, reason });
}

function record(value, keys, path) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
      || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) {
    fail(path, 'expected an object');
  }
  for (const key of Object.keys(value)) {
    if (!keys.includes(key)) fail(`${path}.${key}`, 'unknown property');
  }
  return value;
}

function number(value, path, min, max, integer = false) {
  if (typeof value !== 'number' || !Number.isFinite(value)
      || value < min || value > max || (integer && !Number.isInteger(value))) {
    fail(path, `expected ${integer ? 'an integer' : 'a finite number'} from ${min} through ${max}`);
  }
  return value;
}

function text(value, path, max) {
  if (typeof value !== 'string' || !value.trim() || value.length > max || value.includes('\0')) {
    fail(path, `expected nonempty text of at most ${max} characters without NUL bytes`);
  }
  return value;
}

function color(value, path) {
  if (typeof value !== 'string' || !/^#[0-9a-fA-F]{6}$/.test(value)) {
    fail(path, 'expected a six-digit hexadecimal color such as #142036');
  }
  return value;
}

function source(value, path) {
  text(value, path, 4096);
  if (isAbsolute(value) || /[:\\\u0000-\u001f]/.test(value)
      || value.split('/').includes('..')) {
    fail(path, 'expected a relative local asset path without protocols, backslashes, or parent traversal');
  }
  return value;
}

function list(value, path, min, max) {
  if (!Array.isArray(value) || value.length < min || value.length > max) {
    fail(path, `expected an array with ${min} through ${max} entries`);
  }
  return value;
}

function positiveDuration(value, path, min = Number.MIN_VALUE) {
  return number(value, path, min, 600);
}

function optional(value, fallback) {
  return value === undefined ? fallback : value;
}

function fades(raw, duration, path) {
  const limit = duration * (1 + Number.EPSILON * 8);
  const fadeIn = number(optional(raw.fadeIn, 0), `${path}.fadeIn`, 0, limit);
  const fadeOut = number(optional(raw.fadeOut, 0), `${path}.fadeOut`, 0, limit);
  if (fadeIn + fadeOut > limit) fail(path, 'fade durations must sum to no more than the local duration');
  return { fadeIn, fadeOut };
}

export function validateProject(value) {
  const input = record(value, ['version', 'title', 'canvas', 'clips', 'words', 'captions', 'audio', 'overlays'], 'project');
  if (input.version !== 1) fail('project.version', 'expected version 1');
  const title = text(input.title, 'project.title', 200);
  const rawCanvas = record(input.canvas, ['width', 'height', 'fps'], 'project.canvas');
  const canvas = {
    width: number(rawCanvas.width, 'project.canvas.width', 64, 3840, true),
    height: number(rawCanvas.height, 'project.canvas.height', 64, 3840, true),
    fps: number(rawCanvas.fps, 'project.canvas.fps', 1, 60, true),
  };
  for (const dimension of ['width', 'height']) {
    if (canvas[dimension] % 2 !== 0) fail(`project.canvas.${dimension}`, 'must be even');
  }
  const wordIds = new Map();
  let previousEnd = 0;
  const words = list(optional(input.words, []), 'project.words', 0, 2000).map((raw, index) => {
    const path = `project.words[${index}]`;
    record(raw, ['id', 'text', 'start', 'end'], path);
    if (typeof raw.id !== 'string' || !/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(raw.id)) {
      fail(`${path}.id`, 'expected a word ID starting with a letter and containing at most 64 letters, numbers, underscores, or hyphens');
    }
    if (wordIds.has(raw.id)) fail(`${path}.id`, `duplicate word ID ${raw.id}`);
    const word = {
      id: raw.id, text: text(raw.text, `${path}.text`, 200),
      start: number(raw.start, `${path}.start`, 0, 600),
      end: number(raw.end, `${path}.end`, 0, 600),
    };
    if (word.end <= word.start) fail(`${path}.end`, 'must be after start');
    if (word.start < previousEnd) fail(`${path}.start`, 'words must be chronological and cannot overlap');
    previousEnd = word.end;
    wordIds.set(word.id, index);
    return word;
  });
  const ids = new Set();
  let duration = 0;
  const clips = list(input.clips, 'project.clips', 1, 100).map((raw, index) => {
    const path = `project.clips[${index}]`;
    record(raw, ['id', 'kind', 'color', 'src', 'duration', 'untilWord', 'in', 'volume', 'effects'], path);
    if (typeof raw.id !== 'string' || !/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(raw.id)) {
      fail(`${path}.id`, 'expected an ID starting with a letter and containing at most 64 letters, numbers, underscores, or hyphens');
    }
    if (ids.has(raw.id)) fail(`${path}.id`, `duplicate clip ID ${raw.id}`);
    ids.add(raw.id);
    if (!['color', 'image', 'video'].includes(raw.kind)) fail(`${path}.kind`, 'expected color, image, or video');
    const allowed = raw.kind === 'color' ? ['id', 'kind', 'duration', 'color']
      : raw.kind === 'image' ? ['id', 'kind', 'duration', 'src']
        : ['id', 'kind', 'duration', 'src', 'in', 'volume'];
    record(raw, [...allowed, 'untilWord', 'effects'], path);
    const clip = { id: raw.id, kind: raw.kind };
    const previousDuration = duration;
    let clipDuration;
    if (Object.hasOwn(raw, 'untilWord')) {
      if (Object.hasOwn(raw, 'duration')) fail(path, 'untilWord cannot be mixed with numeric duration');
      if (!wordIds.has(raw.untilWord)) fail(`${path}.untilWord`, 'expected a known word ID');
      const end = words[wordIds.get(raw.untilWord)].end;
      clipDuration = positiveDuration(end - duration, `${path}.untilWord`);
      const roundingTolerance = Number.EPSILON * Math.max(end, duration, 1 / canvas.fps) * 8;
      if (clipDuration + roundingTolerance < 1 / canvas.fps) fail(`${path}.untilWord`, 'must end at least one frame after the preceding clip');
      clip.untilWord = raw.untilWord;
      duration = end;
    } else {
      clipDuration = positiveDuration(raw.duration, `${path}.duration`, 1 / canvas.fps);
      clip.duration = clipDuration;
      duration += clipDuration;
    }
    if (Math.round(duration * canvas.fps) <= Math.round(previousDuration * canvas.fps)) {
      fail(path, 'must span at least one encoded frame');
    }
    if (raw.kind === 'color') clip.color = color(raw.color, `${path}.color`);
    else clip.src = source(raw.src, `${path}.src`);
    if (raw.kind === 'video') {
      clip.in = number(optional(raw.in, 0), `${path}.in`, 0, Number.MAX_SAFE_INTEGER);
      clip.volume = number(optional(raw.volume, 1), `${path}.volume`, 0, 4);
    }
    if (raw.effects !== undefined) {
      const effects = record(raw.effects, ['fadeIn', 'fadeOut', 'zoom', 'brightness', 'contrast', 'saturation'], `${path}.effects`);
      clip.effects = {
        ...fades(effects, clipDuration, `${path}.effects`),
        zoom: number(optional(effects.zoom, 1), `${path}.effects.zoom`, 1, 2),
        brightness: number(optional(effects.brightness, 0), `${path}.effects.brightness`, -1, 1),
        contrast: number(optional(effects.contrast, 1), `${path}.effects.contrast`, 0, 3),
        saturation: number(optional(effects.saturation, 1), `${path}.effects.saturation`, 0, 3),
      };
    }
    return clip;
  });
  if (duration > 600 + 1e-9) fail('project.clips.duration', 'combined duration cannot exceed 600 seconds');
  for (const [index, word] of words.entries()) {
    if (word.end > duration + 1e-9) fail(`project.words[${index}].end`, 'must fit inside the resolved project duration');
  }
  const captions = list(optional(input.captions, []), 'project.captions', 0, 200).map((raw, index) => {
    const path = `project.captions[${index}]`;
    record(raw, ['text', 'start', 'end', 'fromWord', 'toWord', 'position', 'fontSize', 'color'], path);
    const caption = {
      position: optional(raw.position, 'bottom'),
      fontSize: number(optional(raw.fontSize, 48), `${path}.fontSize`, 12, 200, true),
      color: color(optional(raw.color, '#ffffff'), `${path}.color`),
    };
    if (!['top', 'center', 'bottom'].includes(caption.position)) {
      fail(`${path}.position`, 'expected top, center, or bottom');
    }
    if (Object.hasOwn(raw, 'fromWord') || Object.hasOwn(raw, 'toWord')) {
      if (Object.hasOwn(raw, 'start') || Object.hasOwn(raw, 'end')) fail(path, 'word anchors cannot be mixed with explicit start/end');
      if (!wordIds.has(raw.fromWord)) fail(`${path}.fromWord`, 'expected a known word ID');
      if (!wordIds.has(raw.toWord)) fail(`${path}.toWord`, 'expected a known word ID');
      if (wordIds.get(raw.fromWord) > wordIds.get(raw.toWord)) fail(`${path}.toWord`, 'must not precede fromWord');
      caption.fromWord = raw.fromWord;
      caption.toWord = raw.toWord;
      if (raw.text !== undefined) caption.text = text(raw.text, `${path}.text`, 1000);
      // Validate derived text now without freezing the word-dependent value in project JSON.
      resolveAnchor(caption, words, wordIds, path);
    } else {
      caption.text = text(raw.text, `${path}.text`, 1000);
      caption.start = number(raw.start, `${path}.start`, 0, duration);
      caption.end = number(raw.end, `${path}.end`, 0, duration);
      if (caption.end <= caption.start) fail(`${path}.end`, 'must be after start');
    }
    return caption;
  });
  const audio = list(optional(input.audio, []), 'project.audio', 0, 16).map((raw, index) => {
    const path = `project.audio[${index}]`;
    record(raw, ['src', 'start', 'in', 'duration', 'volume', 'fadeIn', 'fadeOut'], path);
    const track = {
      src: source(raw.src, `${path}.src`),
      start: number(raw.start, `${path}.start`, 0, duration),
      in: number(optional(raw.in, 0), `${path}.in`, 0, Number.MAX_SAFE_INTEGER),
      duration: positiveDuration(raw.duration, `${path}.duration`),
      volume: number(optional(raw.volume, 1), `${path}.volume`, 0, 4),
    };
    if (track.start + track.duration > duration + 1e-9) fail(`${path}.duration`, 'track must finish within the project timeline');
    if (raw.fadeIn !== undefined || raw.fadeOut !== undefined) Object.assign(track, fades(raw, track.duration, path));
    return track;
  });
  const overlayIds = new Set();
  const overlays = list(optional(input.overlays, []), 'project.overlays', 0, 32).map((raw, index) => {
    const path = `project.overlays[${index}]`;
    record(raw, ['id', 'kind', 'src', 'start', 'duration', 'fromWord', 'toWord', 'rect', 'in', 'opacity'], path);
    if (typeof raw.id !== 'string' || !/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(raw.id)) fail(`${path}.id`, 'expected a clip-style ID');
    if (overlayIds.has(raw.id)) fail(`${path}.id`, `duplicate overlay ID ${raw.id}`);
    overlayIds.add(raw.id);
    if (!['image', 'video'].includes(raw.kind)) fail(`${path}.kind`, 'expected image or video');
    if (raw.kind === 'image' && Object.hasOwn(raw, 'in')) fail(`${path}.in`, 'image overlays have no source offset');
    const rawRect = record(raw.rect, ['x', 'y', 'width', 'height'], `${path}.rect`);
    const rect = {
      x: number(rawRect.x, `${path}.rect.x`, 0, canvas.width, true),
      y: number(rawRect.y, `${path}.rect.y`, 0, canvas.height, true),
      width: number(rawRect.width, `${path}.rect.width`, 1, canvas.width, true),
      height: number(rawRect.height, `${path}.rect.height`, 1, canvas.height, true),
    };
    if (rect.x + rect.width > canvas.width || rect.y + rect.height > canvas.height) fail(`${path}.rect`, 'must fit inside the canvas');
    const overlay = {
      id: raw.id, kind: raw.kind, src: source(raw.src, `${path}.src`),
      rect, opacity: number(optional(raw.opacity, 1), `${path}.opacity`, 0, 1),
    };
    if (Object.hasOwn(raw, 'fromWord') || Object.hasOwn(raw, 'toWord')) {
      if (Object.hasOwn(raw, 'start') || Object.hasOwn(raw, 'duration')) fail(path, 'word anchors cannot be mixed with numeric start/duration');
      wordWindow(raw, words, wordIds, path);
      overlay.fromWord = raw.fromWord;
      overlay.toWord = raw.toWord;
    } else {
      overlay.start = number(raw.start, `${path}.start`, 0, duration);
      overlay.duration = positiveDuration(raw.duration, `${path}.duration`);
      if (overlay.start + overlay.duration > duration + 1e-9) fail(`${path}.duration`, 'overlay must finish within the project timeline');
    }
    if (raw.kind === 'video') overlay.in = number(optional(raw.in, 0), `${path}.in`, 0, Number.MAX_SAFE_INTEGER);
    return overlay;
  });
  return { version: 1, title, canvas, clips, words, captions, audio, overlays };
}

function wordWindow(raw, words, wordIds, path) {
  if (!wordIds.has(raw.fromWord)) fail(`${path}.fromWord`, 'expected a known word ID');
  if (!wordIds.has(raw.toWord)) fail(`${path}.toWord`, 'expected a known word ID');
  const first = wordIds.get(raw.fromWord);
  const last = wordIds.get(raw.toWord);
  if (first > last) fail(`${path}.toWord`, 'must not precede fromWord');
  return { start: words[first].start, end: words[last].end };
}

function resolveAnchor(caption, words, wordIds, path) {
  const first = wordIds.get(caption.fromWord);
  const last = wordIds.get(caption.toWord);
  const wording = caption.text === undefined ? words.slice(first, last + 1).map((word) => word.text).join(' ') : caption.text;
  return {
    text: text(wording, `${path}.text`, 1000),
    start: words[first].start, end: words[last].end,
    position: caption.position, fontSize: caption.fontSize, color: caption.color,
  };
}

export function resolveCaptions(project) {
  const normalized = validateProject(project);
  const wordIds = new Map(normalized.words.map((word, index) => [word.id, index]));
  return normalized.captions.map((caption, index) => caption.fromWord === undefined
    ? { ...caption }
    : resolveAnchor(caption, normalized.words, wordIds, `project.captions[${index}]`));
}

export function resolveClips(project) {
  const normalized = validateProject(project);
  const ends = new Map(normalized.words.map(word => [word.id, word.end]));
  let elapsed = 0;
  return normalized.clips.map(({ untilWord, ...clip }) => {
    const duration = untilWord === undefined ? clip.duration : ends.get(untilWord) - elapsed;
    elapsed += duration;
    return { ...clip, duration };
  });
}

export function resolveOverlays(project) {
  const normalized = validateProject(project);
  const wordIds = new Map(normalized.words.map((word, index) => [word.id, index]));
  return normalized.overlays.map(({ fromWord, toWord, ...overlay }, index) => {
    if (fromWord === undefined) return overlay;
    const window = wordWindow({ fromWord, toWord }, normalized.words, wordIds, `project.overlays[${index}]`);
    return { ...overlay, start: window.start, duration: window.end - window.start };
  });
}

export async function loadProject(file) {
  let projectPath;
  let content;
  try {
    if (typeof file !== 'string' || !file.trim()) throw new Error('expected a project file path');
    projectPath = await realpath(resolve(file));
    const info = await stat(projectPath);
    if (!info.isFile()) throw new Error('project path is not a regular file');
    if (info.size > 2 * 1024 * 1024) throw new Error('project JSON exceeds the 2 MiB limit');
    content = await readFile(projectPath, 'utf8');
  } catch (error) {
    throw new ProjectError('PROJECT_READ_FAILED', `Cannot read project ${String(file)}: ${error.message}`);
  }
  let value;
  try {
    value = JSON.parse(content);
  } catch (error) {
    throw new ProjectError('INVALID_PROJECT', `Invalid project JSON: ${error.message}`);
  }
  const project = validateProject(value);
  const root = dirname(projectPath);
  await validateAssets(project, root);
  return { project, projectPath, root };
}

export async function validateAssets(project, root) {
  let canonicalRoot;
  try {
    canonicalRoot = await realpath(root);
    if (!(await stat(canonicalRoot)).isDirectory()) throw new Error('project root is not a directory');
  } catch (error) {
    throw new ProjectError('INVALID_ASSET', `Cannot use project asset directory: ${error.message}`);
  }
  const sources = new Set([...project.clips.filter((clip) => clip.src).map((clip) => clip.src),
    ...project.audio.map((track) => track.src), ...(project.overlays ?? []).map((overlay) => overlay.src)]);
  for (const src of sources) {
    try {
      source(src, 'asset.src');
      const canonical = await realpath(resolve(canonicalRoot, src));
      const fromRoot = relative(canonicalRoot, canonical);
      if (isAbsolute(fromRoot) || fromRoot === '..' || fromRoot.startsWith(`..${sep}`)) {
        throw new Error('asset resolves outside the project directory');
      }
      if (!(await stat(canonical)).isFile()) throw new Error('asset is not a regular file');
      await access(canonical, constants.R_OK);
    } catch (error) {
      throw new ProjectError('INVALID_ASSET', `Cannot use asset ${src}: ${error.message}`, { src });
    }
  }
}
