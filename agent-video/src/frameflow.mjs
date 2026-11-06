import { access, realpath, stat } from 'node:fs/promises';
import { constants } from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { probeMedia, STILL_IMAGE_FORMATS } from './render.mjs';

const DAY = 86400;
const EPS = 1e-9;
const codes = { brief: 'INVALID_FRAMEFLOW_BRIEF', inputs: 'INVALID_FRAMEFLOW_INPUTS', board: 'INVALID_FRAMEFLOW_STORYBOARD', timings: 'INVALID_FRAMEFLOW_TIMINGS', file: 'INVALID_FRAMEFLOW_FILE' };

function fail(code, path, reason) {
  throw Object.assign(new Error(`${path}: ${reason}`), { code, details: { path, reason } });
}
function record(value, allowed, path, code) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) fail(code, path, 'expected an object');
  for (const key of Object.keys(value)) if (!allowed.includes(key)) fail(code, `${path}.${key}`, 'unknown property');
  return value;
}
function number(value, path, code, min = 0, max = DAY, integer = false) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max || (integer && !Number.isInteger(value))) fail(code, path, `expected ${integer ? 'an integer' : 'a finite number'} from ${min} through ${max}`);
  return value;
}
function text(value, path, code, max = 2000, allowEmpty = false) {
  if (typeof value !== 'string' || (!allowEmpty && !value.trim()) || value.length > max || value.includes('\0')) fail(code, path, `expected ${allowEmpty ? '' : 'nonempty '}text of at most ${max} characters without NUL bytes`);
  return value;
}
function list(value, path, code, maximum, fallback = false) {
  if (value === undefined && fallback) return [];
  if (!Array.isArray(value) || value.length > maximum) fail(code, path, `expected an array with at most ${maximum} entries`);
  return value;
}
function positive(value, path, code, max = DAY) { return number(value, path, code, Number.MIN_VALUE, max); }
function localPath(value, baseDir, path, code) {
  text(value, path, code, 4096);
  if (/^[\\/]{2}/.test(value) || /[\u0000-\u001f]/.test(value)
    || (value.includes(':') && !/^[A-Za-z]:[\\/][^:]*$/.test(value))
    || (process.platform !== 'win32' && /^[A-Za-z]:/.test(value))) fail(code, path, 'use a local file path without URLs, protocols, network shares, or drive-relative paths');
  return resolve(baseDir, value);
}
function uniqueAliases(entries, aliases, path) {
  const seen = new Map();
  for (const [index, entry] of entries.entries()) for (const alias of new Set(aliases(entry).map(value => value.toLowerCase()))) {
    if (seen.has(alias) && seen.get(alias) !== index) fail(codes.inputs, path, `ambiguous or duplicate source basename ${alias}`);
    seen.set(alias, index);
  }
}

export function validateBrief(value) {
  const code = codes.brief;
  const raw = record(value, ['title', 'format', 'aspect', 'fps', 'target_seconds', 'audience', 'tone', 'summary', 'skills', 'open_questions'], 'brief', code);
  const result = {};
  for (const field of ['title', 'format', 'audience', 'tone', 'summary']) result[field] = text(raw[field], `brief.${field}`, code, field === 'summary' ? 10000 : 1000);
  if (!['16:9', '9:16', '1:1'].includes(raw.aspect)) fail(code, 'brief.aspect', 'expected 16:9, 9:16, or 1:1');
  result.aspect = raw.aspect;
  result.fps = raw.fps === undefined ? 30 : raw.fps;
  if (![24, 25, 30, 60].includes(result.fps)) fail(code, 'brief.fps', 'expected 24, 25, 30, or 60');
  result.target_seconds = positive(raw.target_seconds, 'brief.target_seconds', code);
  if (raw.skills !== undefined) result.skills = list(raw.skills, 'brief.skills', code, 32).map((item, index) => {
    const path = `brief.skills[${index}]`;
    record(item, ['name', 'why'], path, code);
    return { name: text(item.name, `${path}.name`, code, 200), why: text(item.why, `${path}.why`, code) };
  });
  if (raw.open_questions !== undefined) result.open_questions = list(raw.open_questions, 'brief.open_questions', code, 32).map((item, index) => text(item, `brief.open_questions[${index}]`, code));
  return result;
}

export function validateInputs(value, { baseDir = process.cwd() } = {}) {
  const code = codes.inputs;
  const raw = record(value, ['footage', 'assets', 'music', 'prompt', 'script'], 'inputs', code);
  const result = {
    footage: list(raw.footage, 'inputs.footage', code, 100, true).map((entry, index) => {
      const path = `inputs.footage[${index}]`;
      record(entry, ['name', 'source', 'duration', 'folder'], path, code);
      const name = text(entry.name, `${path}.name`, code, 255);
      if (/[\\/:\u0000-\u001f]/.test(name) || ['.', '..'].includes(name)) fail(code, `${path}.name`, 'expected an unambiguous recording file name');
      return { name, source: localPath(entry.source, baseDir, `${path}.source`, code), duration: positive(entry.duration, `${path}.duration`, code), ...(entry.folder === undefined ? {} : { folder: localPath(entry.folder, baseDir, `${path}.folder`, code) }) };
    }),
    assets: list(raw.assets, 'inputs.assets', code, 256, true).map((entry, index) => {
      const path = `inputs.assets[${index}]`;
      record(entry, ['path', 'kind', 'duration', 'size'], path, code);
      if (!['image', 'clip'].includes(entry.kind)) fail(code, `${path}.kind`, 'expected image or clip');
      const asset = { path: localPath(entry.path, baseDir, `${path}.path`, code), kind: entry.kind };
      if (entry.kind === 'clip' || entry.duration !== undefined) asset.duration = positive(entry.duration, `${path}.duration`, code);
      if (entry.size !== undefined) {
        if (typeof entry.size !== 'string' || !/^[1-9][0-9]{0,5}x[1-9][0-9]{0,5}$/.test(entry.size)) fail(code, `${path}.size`, 'expected dimensions such as 1920x1080');
        asset.size = entry.size;
      }
      return asset;
    }),
    music: list(raw.music, 'inputs.music', code, 32, true).map((entry, index) => {
      const path = `inputs.music[${index}]`;
      record(entry, ['path', 'duration'], path, code);
      return { path: localPath(entry.path, baseDir, `${path}.path`, code), ...(entry.duration === undefined ? {} : { duration: positive(entry.duration, `${path}.duration`, code) }) };
    }),
  };
  if (raw.prompt !== undefined) result.prompt = text(raw.prompt, 'inputs.prompt', code, 20000, true);
  if (raw.script !== undefined) result.script = raw.script === null ? null : text(raw.script, 'inputs.script', code, 100000, true);
  uniqueAliases(result.footage, entry => [entry.name, basename(entry.source)], 'inputs.footage');
  uniqueAliases(result.assets, entry => [basename(entry.path)], 'inputs.assets');
  uniqueAliases(result.music, entry => [basename(entry.path)], 'inputs.music');
  return result;
}

export function validateTimings(value, supplied) {
  const inputs = validateInputs(supplied);
  const recordings = new Map(inputs.footage.map(entry => [entry.name, entry]));
  record(value, [...recordings.keys()], 'timings', codes.timings);
  const result = {};
  for (const [name, raw] of Object.entries(value)) {
    const path = `timings.${name}`;
    record(raw, ['pauses', 'words'], path, codes.timings);
    const duration = recordings.get(name).duration;
    function intervals(rows, field, maximum) {
      let previousEnd = 0;
      const ids = new Set();
      return list(rows, `${path}.${field}`, codes.timings, maximum).map((entry, index) => {
        const item = `${path}.${field}[${index}]`;
        record(entry, field === 'words' ? ['id', 'text', 'start', 'end'] : ['start', 'end'], item, codes.timings);
        const normalized = { start: number(entry.start, `${item}.start`, codes.timings, 0, duration), end: number(entry.end, `${item}.end`, codes.timings, 0, duration) };
        if (normalized.end <= normalized.start || normalized.start < previousEnd) fail(codes.timings, item, 'intervals must be chronological, non-overlapping, and have positive duration');
        previousEnd = normalized.end;
        if (field === 'words') {
          normalized.text = text(entry.text, `${item}.text`, codes.timings, 200);
          if (entry.id !== undefined) {
            normalized.id = text(entry.id, `${item}.id`, codes.timings, 64);
            if (ids.has(normalized.id)) fail(codes.timings, `${item}.id`, 'duplicate word ID');
            ids.add(normalized.id);
          }
        }
        return normalized;
      });
    }
    Object.defineProperty(result, name, {
      value: { pauses: intervals(raw.pauses, 'pauses', 10000), ...(raw.words === undefined ? {} : { words: intervals(raw.words, 'words', 20000) }) },
      enumerable: true, configurable: true, writable: true,
    });
  }
  return result;
}

function sourceMatch(value, entries, key, baseDir, path) {
  const absolute = localPath(value, baseDir, path, codes.board);
  const plainName = !/[\\/]/.test(value);
  const matches = entries.filter(entry => entry[key].toLowerCase() === absolute.toLowerCase()
    || (plainName && (entry.name?.toLowerCase() === value.toLowerCase() || basename(entry[key]).toLowerCase() === value.toLowerCase())));
  if (matches.length !== 1) fail(codes.board, path, matches.length ? 'ambiguous source reference' : 'source is not in the supplied inventory');
  return matches[0];
}

// Frameflow uses Python round(): exact half-frame ties choose the even frame.
function frame(seconds, fps) {
  const scaled = seconds * fps;
  const lower = Math.floor(scaled);
  return scaled - lower === 0.5 ? lower + lower % 2 : Math.round(scaled);
}
function safeBoundary(time, recording, pauses, fps, path) {
  if (Math.abs(time) <= EPS || Math.abs(time - recording.duration) <= EPS) return;
  const quantized = frame(time, fps) / fps;
  const period = 1 / fps;
  const pause = pauses.find(value => time >= value.start - EPS && time <= value.end + EPS);
  if (!pause || pause.end - pause.start < 3 * period - EPS
    || quantized < pause.start + period - EPS || quantized > pause.end - period + EPS) {
    fail('UNSAFE_FRAMEFLOW_CUT', path, 'interior source boundaries require a measured pause at least three frames long and must retain one-frame margins after project-frame rounding');
  }
}

function cutawayWindow(asset, item, sceneSeconds, fps, path, code) {
  const requested = item.duration === undefined ? 3 : positive(item.duration, `${path}.duration`, code);
  const duration = frame(Math.min(requested, sceneSeconds), fps) / fps;
  if (duration < 1 / fps) fail(code, path, 'B-roll rounds to fewer than one project frame');
  if (asset.kind === 'image' && item.start !== undefined) fail(code, `${path}.start`, 'a still image has no source offset');
  if (asset.kind === 'clip') {
    const offset = item.start === undefined ? 0 : number(item.start, `${path}.start`, code, 0, asset.duration);
    const start = frame(offset, fps) / fps;
    if (start + duration > asset.duration + 0.001 + EPS) fail(code, path, 'B-roll exceeds its supplied clip after project-frame rounding; provide a longer clip or a shorter explicit duration');
  }
}

export function validateStoryboard(value, { inputs: rawInputs, brief: rawBrief, timings: rawTimings = {}, baseDir = process.cwd() } = {}) {
  const code = codes.board;
  if (value && Object.hasOwn(value, 'voice')) fail('GENERATION_NOT_ALLOWED', 'storyboard.voice', 'voice generation is excluded');
  const raw = record(value, ['script', 'scenes', 'music', 'spoken_captions'], 'storyboard', code);
  const brief = validateBrief(rawBrief);
  if (brief.open_questions?.length) fail(codes.brief, 'brief.open_questions', 'resolve the creative brief questions before proposing a storyboard');
  const inputs = validateInputs(rawInputs, { baseDir });
  const timings = validateTimings(rawTimings, inputs);
  const requirements = new Set(['native-project-export', 'human-edit-reconciliation', 'source-normalization-review']);
  const warnings = [];
  const storyboard = { script: text(raw.script, 'storyboard.script', code, 100000), scenes: [] };
  if (raw.spoken_captions !== undefined) {
    if (typeof raw.spoken_captions !== 'boolean') fail(code, 'storyboard.spoken_captions', 'expected a boolean');
    storyboard.spoken_captions = raw.spoken_captions;
    if (raw.spoken_captions) requirements.add('caption-rendering');
  }
  if (raw.music !== undefined) {
    record(raw.music, ['path', 'volume_db', 'cut_to_beat'], 'storyboard.music', code);
    const music = sourceMatch(raw.music.path, inputs.music, 'path', baseDir, 'storyboard.music.path');
    storyboard.music = { path: music.path, ...(raw.music.volume_db === undefined ? {} : { volume_db: number(raw.music.volume_db, 'storyboard.music.volume_db', code, -120, 0) }) };
    requirements.add('music-mixing');
    if (raw.music.cut_to_beat !== undefined) {
      if (typeof raw.music.cut_to_beat !== 'boolean') fail(code, 'storyboard.music.cut_to_beat', 'expected a boolean');
      storyboard.music.cut_to_beat = raw.music.cut_to_beat;
      if (raw.music.cut_to_beat) {
        requirements.add('beat-timing-rebuild');
        warnings.push('Timeline and source mappings are provisional: Frameflow must measure music beats, rebuild timing, and recheck source windows and speech cuts before rendering.');
      }
    }
  }
  const scenes = list(raw.scenes, 'storyboard.scenes', code, 100);
  if (!scenes.length) fail(code, 'storyboard.scenes', 'at least one scene is required');
  const timeline = [];
  let totalFrames = 0;
  for (const [index, item] of scenes.entries()) {
    const path = `storyboard.scenes[${index}]`;
    if (item && Object.hasOwn(item, 'narration')) fail('GENERATION_NOT_ALLOWED', `${path}.narration`, 'narration generation is excluded; use supplied recording sound');
    record(item, ['visual', 'reason', 'duration', 'caption', 'cards', 'broll'], path, code);
    const scene = { reason: text(item.reason, `${path}.reason`, code) };
    const visual = item.visual;
    record(visual, ['type', 'source', 'start', 'end', 'path', 'text'], `${path}.visual`, code);
    let source;
    let sourceIn;
    let sourceOut;
    let frames;
    if (visual.type === 'footage') {
      record(visual, ['type', 'source', 'start', 'end'], `${path}.visual`, code);
      const recording = sourceMatch(visual.source, inputs.footage, 'source', baseDir, `${path}.visual.source`);
      sourceIn = number(visual.start, `${path}.visual.start`, code, 0, recording.duration);
      sourceOut = number(visual.end, `${path}.visual.end`, code, 0, recording.duration);
      if (sourceOut <= sourceIn) fail(code, `${path}.visual.end`, 'must be after start');
      if (item.duration !== undefined && Math.abs(positive(item.duration, `${path}.duration`, code) - (sourceOut - sourceIn)) > EPS) fail(code, `${path}.duration`, 'footage duration is fixed by its selected source span');
      const pauses = timings[recording.name]?.pauses ?? [];
      safeBoundary(sourceIn, recording, pauses, brief.fps, `${path}.visual.start`);
      safeBoundary(sourceOut, recording, pauses, brief.fps, `${path}.visual.end`);
      source = recording.source;
      scene.visual = { type: 'footage', source: recording.name, start: sourceIn, end: sourceOut };
      frames = frame(sourceOut, brief.fps) - frame(sourceIn, brief.fps);
      if (Math.abs(frame(sourceIn, brief.fps) / brief.fps - sourceIn) > EPS || Math.abs(frame(sourceOut, brief.fps) / brief.fps - sourceOut) > EPS) warnings.push(`Scene ${index + 1}: source seconds are preserved; Frameflow quantizes their boundaries to ${brief.fps} fps.`);
      requirements.add('speech-cut-review');
    } else if (visual.type === 'asset') {
      record(visual, ['type', 'path', 'start'], `${path}.visual`, code);
      const asset = sourceMatch(visual.path, inputs.assets, 'path', baseDir, `${path}.visual.path`);
      source = asset.path;
      scene.visual = { type: 'asset', path: asset.path };
      let duration;
      if (asset.kind === 'image') {
        if (visual.start !== undefined) fail(code, `${path}.visual.start`, 'a still image has no source offset');
        duration = positive(item.duration, `${path}.duration`, code);
      } else {
        sourceIn = number(visual.start === undefined ? 0 : visual.start, `${path}.visual.start`, code, 0, asset.duration);
        duration = item.duration === undefined ? asset.duration - sourceIn : positive(item.duration, `${path}.duration`, code);
        sourceOut = sourceIn + duration;
        if (duration <= 0 || sourceOut > asset.duration + EPS) fail(code, `${path}.duration`, 'the entire selected clip window must fit inside the supplied asset');
        scene.visual.start = sourceIn;
      }
      scene.duration = duration;
      frames = frame(duration, brief.fps);
      if (asset.kind === 'clip' && (frame(sourceIn, brief.fps) + frames) / brief.fps > asset.duration + 0.001 + EPS) fail(code, `${path}.duration`, 'the selected asset window exceeds its source after Frameflow rounds the start and length; choose a safe frame-aligned interval');
      if (asset.kind === 'clip' && Math.abs(frame(sourceIn, brief.fps) / brief.fps - sourceIn) > EPS) warnings.push(`Scene ${index + 1}: source offset seconds are preserved; Frameflow quantizes the offset to ${brief.fps} fps.`);
      if (Math.abs(frames / brief.fps - duration) > EPS) warnings.push(`Scene ${index + 1}: Frameflow quantizes its duration to ${brief.fps} fps.`);
    } else if (visual.type === 'title' || visual.type === 'composition') {
      record(visual, visual.type === 'title' ? ['type', 'text'] : ['type', 'path'], `${path}.visual`, code);
      scene.visual = visual.type === 'title' ? { type: 'title', text: text(visual.text, `${path}.visual.text`, code, 2000) }
        : { type: 'composition', path: localPath(visual.path, baseDir, `${path}.visual.path`, code) };
      scene.duration = positive(item.duration, `${path}.duration`, code);
      frames = frame(scene.duration, brief.fps);
      requirements.add(visual.type === 'title' ? 'title-rendering' : 'custom-html-composition');
    } else fail(code, `${path}.visual.type`, 'expected footage, asset, title, or composition');
    if (frames < 1) fail(code, `${path}.duration`, 'scene rounds to fewer than one project frame');
    if (item.duration !== undefined && scene.duration === undefined) scene.duration = item.duration;
    if (item.caption !== undefined) {
      scene.caption = text(item.caption, `${path}.caption`, code, 2000);
      requirements.add('caption-rendering');
    }
    if (item.cards !== undefined) {
      if (!['footage', 'asset'].includes(visual.type)) fail(code, `${path}.cards`, 'cards require footage or a supplied asset');
      scene.cards = list(item.cards, `${path}.cards`, code, 32).map((card, cardIndex) => {
        const cardPath = `${path}.cards[${cardIndex}]`;
        record(card, ['kind', 'text', 'subtitle', 'price', 'when', 'duration'], cardPath, code);
        if (!['product', 'lower_third'].includes(card.kind)) fail(code, `${cardPath}.kind`, 'expected product or lower_third');
        if (card.kind === 'lower_third' && card.price !== undefined) fail(code, `${cardPath}.price`, 'lower thirds have no price');
        const normalized = { kind: card.kind, text: text(card.text, `${cardPath}.text`, code, 500) };
        for (const field of ['subtitle', 'price', 'when']) if (card[field] !== undefined) normalized[field] = text(card[field], `${cardPath}.${field}`, code, 1000);
        if (card.duration !== undefined) normalized.duration = positive(card.duration, `${cardPath}.duration`, code);
        return normalized;
      });
      if (!scene.cards.length) fail(code, `${path}.cards`, 'cards must not be empty');
      requirements.add('card-rendering');
    }
    if (item.broll !== undefined) {
      if (visual.type !== 'footage') fail(code, `${path}.broll`, 'B-roll requires a footage scene');
      scene.broll = list(item.broll, `${path}.broll`, code, 32).map((item, brollIndex) => {
        const itemPath = `${path}.broll[${brollIndex}]`;
        record(item, ['path', 'when', 'duration', 'start'], itemPath, code);
        const asset = sourceMatch(item.path, inputs.assets, 'path', baseDir, `${itemPath}.path`);
        const normalized = { path: asset.path };
        if (item.start !== undefined) {
          if (asset.kind === 'image') fail(code, `${itemPath}.start`, 'a still image has no source offset');
          normalized.start = number(item.start, `${itemPath}.start`, code, 0, asset.duration);
        }
        if (item.duration !== undefined) normalized.duration = positive(item.duration, `${itemPath}.duration`, code);
        if (item.when !== undefined) {
          normalized.when = text(item.when, `${itemPath}.when`, code, 1000);
          requirements.add('phrase-anchor-review');
        }
        cutawayWindow(asset, normalized, frames / brief.fps, brief.fps, itemPath, code);
        return normalized;
      });
      if (!scene.broll.length) fail(code, `${path}.broll`, 'B-roll must not be empty');
      requirements.add('broll-placement');
      warnings.push(`Scene ${index + 1}: Frameflow must resolve any B-roll phrase anchors, clamp placement to the actual scene, and check overlapping cutaways; this handoff does not invent event times.`);
    }
    const start = totalFrames / brief.fps;
    totalFrames += frames;
    if (totalFrames / brief.fps > DAY + EPS) fail(code, 'storyboard.scenes', 'the storyboard exceeds 24 hours');
    timeline.push({ index, start, end: totalFrames / brief.fps, duration: frames / brief.fps, visual: scene.visual, ...(source === undefined ? {} : { source }), ...(sourceIn === undefined ? {} : { sourceIn, sourceOut }) });
    storyboard.scenes.push(scene);
  }
  const duration = totalFrames / brief.fps;
  if (Math.abs(duration - brief.target_seconds) > Math.max(1 / brief.fps, brief.target_seconds * 0.1)) warnings.push(`Storyboard duration ${duration}s differs from the brief target ${brief.target_seconds}s; review pacing before building.`);
  return { storyboard, duration, timeline, requirements: [...requirements], warnings };
}

function rate(stream) {
  for (const value of [stream?.avg_frame_rate, stream?.r_frame_rate]) {
    const [numerator, denominator = 1] = String(value).split('/').map(Number);
    const result = numerator / denominator;
    if (Number.isFinite(result) && result > 0) return result;
  }
  return undefined;
}

function checkCancelled(signal) {
  if (signal?.aborted) fail('CANCELLED', 'frameflow', 'file verification was cancelled');
}

export async function checkFrameflowFiles(rawInputs, storyboard, { signal, brief } = {}) {
  checkCancelled(signal);
  if (storyboard !== undefined && brief === undefined) fail(codes.file, 'brief', 'an explicit project brief is required to verify storyboard source windows on the target frame grid');
  const fps = storyboard === undefined ? undefined : validateBrief(brief).fps;
  const inputs = validateInputs(rawInputs);
  const files = [];
  const measured = new Map();
  const entries = [...inputs.footage.map(entry => ({ ...entry, path: entry.source, kind: 'footage' })), ...inputs.assets, ...inputs.music.map(entry => ({ ...entry, kind: 'music' }))];
  for (const entry of entries) {
    checkCancelled(signal);
    try {
      const path = await realpath(entry.path);
      if (!(await stat(path)).isFile()) throw new Error('not a regular file');
      await access(path, constants.R_OK);
      const metadata = await probeMedia(path, { signal });
      const video = metadata.streams.find(stream => stream.codec_type === 'video' && !stream.disposition?.attached_pic);
      const audio = metadata.streams.find(stream => stream.codec_type === 'audio');
      const fps = rate(video);
      let duration;
      if (entry.kind === 'image') {
        if (!STILL_IMAGE_FORMATS.includes(metadata.format?.format_name)) throw new Error('expected a supported self-contained still image');
      } else {
        const stream = entry.kind === 'music' ? audio : video;
        if (!stream) throw new Error(`no ${entry.kind === 'music' ? 'audio' : 'video'} stream`);
        duration = Number(metadata.format?.duration ?? stream.duration);
        if (!Number.isFinite(duration) || duration <= 0 || duration > DAY) throw new Error('media duration must be known, positive, and at most 24 hours');
        // Inventory duration describes actual metadata, not a frame-rounded scene.
        const tolerance = 0.001;
        if (entry.duration !== undefined && Math.abs(entry.duration - duration) > tolerance + EPS) throw new Error(`advertised duration ${entry.duration}s differs from measured duration ${duration}s`);
      }
      const file = { path, kind: entry.kind, ...(duration === undefined ? {} : { duration }), ...(video ? { width: video.width, height: video.height, ...(fps ? { fps } : {}) } : {}) };
      files.push(file);
      measured.set(entry.path, file);
    } catch (error) {
      checkCancelled(signal);
      fail(codes.file, entry.path, error.message);
    }
  }
  if (storyboard !== undefined) {
    const scenes = list(storyboard?.scenes, 'storyboard.scenes', codes.file, 100);
    for (const [index, scene] of scenes.entries()) {
      checkCancelled(signal);
      const visual = scene?.visual;
      if (!visual || typeof visual !== 'object') fail(codes.file, `storyboard.scenes[${index}].visual`, 'expected a validated visual');
      if (visual.type === 'composition') {
        const path = localPath(visual.path, process.cwd(), `storyboard.scenes[${index}].visual.path`, codes.file);
        try {
          if (!(await stat(path)).isDirectory() || !(await stat(join(path, 'index.html'))).isFile()) throw new Error('a composition requires an existing folder and regular index.html');
          await access(join(path, 'index.html'), constants.R_OK);
          files.push({ path: await realpath(join(path, 'index.html')), kind: 'composition' });
        } catch (error) { fail(codes.file, path, error.message); }
      } else if (visual.type === 'footage' || visual.type === 'asset') {
        const entry = visual.type === 'footage' ? inputs.footage.find(item => item.name === visual.source) : inputs.assets.find(item => item.path === visual.path);
        if (!entry) fail(codes.file, `storyboard.scenes[${index}].visual`, 'source is not in the normalized inventory');
        const file = measured.get(entry.source ?? entry.path);
        if (file.duration !== undefined) {
          const start = visual.start ?? 0;
          const end = visual.type === 'footage' ? visual.end : start + (scene.duration ?? entry.duration - start);
          if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start || end > file.duration + 0.001 + EPS) fail(codes.file, `storyboard.scenes[${index}]`, 'selected source window exceeds actual media duration');
          if (visual.type === 'asset') {
            const alignedStart = frame(start, fps) / fps;
            const alignedLength = frame(scene.duration ?? entry.duration - alignedStart, fps) / fps;
            if (alignedStart + alignedLength > file.duration + 0.001 + EPS) fail(codes.file, `storyboard.scenes[${index}]`, 'Frameflow-rounded asset window exceeds actual media duration');
          }
        }
      }
      if (scene.broll !== undefined) {
        if (visual.type !== 'footage') fail(codes.file, `storyboard.scenes[${index}].broll`, 'B-roll requires a footage scene');
        const sceneSeconds = (frame(visual.end, fps) - frame(visual.start, fps)) / fps;
        for (const [brollIndex, item] of list(scene.broll, `storyboard.scenes[${index}].broll`, codes.file, 32).entries()) {
          const path = `storyboard.scenes[${index}].broll[${brollIndex}]`;
          record(item, ['path', 'when', 'duration', 'start'], path, codes.file);
          const asset = inputs.assets.find(entry => entry.path === item.path);
          if (!asset) fail(codes.file, path, 'B-roll source is not in the normalized inventory');
          const file = measured.get(asset.path);
          cutawayWindow({ ...asset, ...(file.duration === undefined ? {} : { duration: file.duration }) }, item, sceneSeconds, fps, path, codes.file);
        }
      }
    }
  }
  checkCancelled(signal);
  return { files, checked: true };
}
