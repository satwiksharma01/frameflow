import { spawn } from 'node:child_process';
import { constants, createReadStream } from 'node:fs';
import { access, copyFile, lstat, open, rename, stat, unlink, writeFile } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import { join, resolve } from 'node:path';
import { resolveCaptions, resolveClips, resolveOverlays, validateProject } from './project.mjs';

function failure(code, message) {
  return Object.assign(new Error(message), { code });
}

function run(executable, args, { cwd, signal } = {}) {
  return new Promise((resolveResult, reject) => {
    let stdout = '';
    let stderr = '';
    let processError;
    const child = spawn(executable, args, {
      cwd, signal, shell: false, windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const deadline = setTimeout(() => child.kill(), 30 * 60 * 1000);
    deadline.unref();
    child.stdout.setEncoding('utf8').on('data', data => { stdout = (stdout + data).slice(-2 * 1024 * 1024); });
    child.stderr.setEncoding('utf8').on('data', data => { stderr = (stderr + data).slice(-16384); });
    child.on('error', error => { processError = error; });
    child.on('close', code => {
      clearTimeout(deadline);
      if (signal?.aborted) return reject(failure('CANCELLED', 'Rendering was cancelled.'));
      if (processError?.code === 'ENOENT') return reject(failure('TOOL_UNAVAILABLE', `Cannot start ${executable}. Install FFmpeg and FFprobe or set FFMPEG_PATH and FFPROBE_PATH to their executables.`));
      if (processError) return reject(failure('TOOL_FAILED', `Cannot start ${executable}: ${processError.message}`));
      if (code !== 0) return reject(failure('TOOL_FAILED', `${executable} failed (exit ${code}): ${stderr.trim()}`));
      resolveResult(stdout);
    });
  });
}

const ffmpeg = () => process.env.FFMPEG_PATH || 'ffmpeg';
const ffprobe = () => process.env.FFPROBE_PATH || 'ffprobe';
const quiet = ['-hide_banner', '-loglevel', 'error', '-nostdin'];
export const STILL_IMAGE_FORMATS = ['png_pipe', 'jpeg_pipe', 'webp_pipe', 'bmp_pipe', 'tiff_pipe'];
export const SUPPORTED_INPUT_FORMATS = [
  'mov', 'mp4', 'm4a', '3gp', '3g2', 'mj2', 'matroska', 'webm', 'avi',
  'mp3', 'aac', 'wav', 'flac', 'ogg', 'mpegts', ...STILL_IMAGE_FORMATS,
].join(',');
const localInput = ['-protocol_whitelist', 'file,pipe', '-format_whitelist', SUPPORTED_INPUT_FORMATS];

async function imageFormat(path) {
  const file = await open(path, 'r');
  const header = Buffer.alloc(16);
  try { await file.read(header, 0, header.length, 0); } finally { await file.close(); }
  if (header.subarray(0, 8).toString('hex') === '89504e470d0a1a0a') return 'png_pipe';
  if (header.subarray(0, 3).toString('hex') === 'ffd8ff') return 'jpeg_pipe';
  if (header.subarray(0, 4).toString() === 'RIFF' && header.subarray(8, 12).toString() === 'WEBP') return 'webp_pipe';
  if (header.subarray(0, 2).toString() === 'BM') return 'bmp_pipe';
  if (['49492a00', '4d4d002a', '49492b00', '4d4d002b'].includes(header.subarray(0, 4).toString('hex'))) return 'tiff_pipe';
  return undefined;
}

function inputOptions(format) {
  // A typed pipe demuxer reads this file alone, without image2 filename expansion.
  return [...localInput, ...(STILL_IMAGE_FORMATS.includes(format) ? ['-f', format] : [])];
}

export async function checkTools() {
  const [encoder, probe] = await Promise.all([
    run(ffmpeg(), ['-version']), run(ffprobe(), ['-version']),
  ]);
  return { ffmpeg: encoder.split(/\r?\n/)[0], ffprobe: probe.split(/\r?\n/)[0] };
}

export async function probeMedia(path, { signal } = {}) {
  const format = await imageFormat(path);
  const output = await run(ffprobe(), [
    '-v', 'error', ...inputOptions(format),
    '-show_format', '-show_streams', '-of', 'json', '-i', resolve(path),
  ], { signal });
  try {
    const result = JSON.parse(output);
    if (!Array.isArray(result.streams)) throw new Error('missing streams');
    return result;
  } catch {
    throw failure('INVALID_MEDIA', `FFprobe did not return readable stream metadata for ${path}.`);
  }
}

function checkInterval(metadata, kind, offset, duration, name) {
  const stream = metadata.streams.find(stream => stream.codec_type === kind);
  if (!stream) throw failure('INVALID_MEDIA', `${name} has no ${kind} stream.`);
  const available = Number(stream.duration ?? metadata.format?.duration);
  if (!Number.isFinite(available)) throw failure('INVALID_MEDIA', `Cannot determine ${kind} duration for ${name}.`);
  if (offset + duration > available + 0.000001) {
    throw failure('MEDIA_TOO_SHORT', `${name} needs ${offset + duration}s of ${kind}, but has ${available}s.`);
  }
}

async function prepareFont(workDir) {
  const candidates = [
    join(process.env.WINDIR || 'C:\\Windows', 'Fonts', 'arial.ttf'),
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
    '/System/Library/Fonts/Supplemental/Arial.ttf',
    '/Library/Fonts/Arial.ttf',
  ];
  for (const file of candidates) {
    try { await access(file); } catch { continue; }
    await copyFile(file, join(workDir, 'caption-font.ttf'));
    return;
  }
  throw failure('FONT_UNAVAILABLE', 'Captions need Arial, DejaVu Sans, or Liberation Sans installed locally.');
}

async function fileDigest(file, signal) {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(file, { signal })) hash.update(chunk);
  return hash.digest('hex');
}

async function reuseSegment(entry, destination, signal) {
  if (!entry) return false;
  try {
    if (!(await lstat(entry.file)).isFile() || await fileDigest(entry.file, signal) !== entry.sha256) return false;
    await copyFile(entry.file, destination, constants.COPYFILE_EXCL);
    if (await fileDigest(destination, signal) === entry.sha256) return true;
    await unlink(destination);
    return false;
  } catch (error) {
    if (error.code === 'ENOENT') return false;
    throw error;
  }
}

async function saveSegments(workDir, segments) {
  const temporary = join(workDir, `segments-${randomUUID()}.tmp`);
  const file = await open(temporary, 'wx');
  try {
    await file.writeFile(JSON.stringify({ version: 1, segments }, null, 2), 'utf8');
    await file.close();
    await rename(temporary, join(workDir, 'segments.json'));
  } catch (error) {
    await file.close().catch(() => {});
    await unlink(temporary).catch(() => {});
    throw error;
  }
}

export async function renderVideo(loaded, { workDir, onProgress = () => {}, signal, clipCache } = {}) {
  const { root } = loaded;
  const project = validateProject(loaded.project);
  const { width, height, fps } = project.canvas;
  const timedCaptions = resolveCaptions(project);
  const clips = resolveClips(project);
  const overlays = resolveOverlays(project);
  const cache = { hits: 0, misses: 0 };
  const encoder = `${ffmpeg()}:${(await run(ffmpeg(), ['-version'], { signal })).split(/\r?\n/)[0]}`;
  const sourceDigests = new Map();
  const media = new Map();
  const files = [...new Set([
    ...clips.filter(clip => clip.kind !== 'color').map(clip => clip.src),
    ...project.audio.map(track => track.src),
    ...overlays.map(overlay => overlay.src),
  ])];
  for (const [index, src] of files.entries()) {
    media.set(src, await probeMedia(resolve(root, src), { signal }));
    await onProgress({ stage: 'probe', completed: index + 1, total: files.length });
  }
  for (const clip of [...clips, ...overlays]) {
    if (clip.kind === 'video') checkInterval(media.get(clip.src), 'video', clip.in, clip.duration, clip.src);
    if (clip.kind === 'image' && !STILL_IMAGE_FORMATS.includes(media.get(clip.src).format?.format_name)) {
      throw failure('INVALID_MEDIA', `${clip.src} must be a PNG, JPEG, WebP, BMP, or TIFF still image.`);
    }
  }
  for (const track of project.audio) checkInterval(media.get(track.src), 'audio', track.in, track.duration, track.src);

  let requestedTime = 0;
  let previousFrame = 0;
  const segments = [];
  const segmentMetadata = [];
  for (const [index, clip] of clips.entries()) {
    requestedTime += clip.duration;
    const endFrame = Math.round(requestedTime * fps);
    const frameCount = endFrame - previousFrame;
    previousFrame = endFrame;
    const duration = frameCount / fps;
    const segment = join(workDir, `clip-${index}.mp4`);
    const effects = clip.effects ?? { fadeIn: 0, fadeOut: 0, zoom: 1, brightness: 0, contrast: 1, saturation: 1 };
    if (clip.src && !sourceDigests.has(clip.src)) sourceDigests.set(clip.src, await fileDigest(resolve(root, clip.src), signal));
    const key = createHash('sha256').update(JSON.stringify({ cacheVersion: 3, encoder, canvas: project.canvas, frameCount, kind: clip.kind, material: clip.color ?? sourceDigests.get(clip.src), in: clip.in ?? 0, volume: clip.volume ?? 1, effects })).digest('hex');
    signal?.throwIfAborted();
    const reused = await reuseSegment(clipCache?.get(key), segment, signal);
    if (reused) cache.hits++;
    else {
      cache.misses++;
      const args = [...quiet];
      if (clip.kind === 'color') {
        args.push('-f', 'lavfi', '-i', `color=c=${clip.color}:s=${width}x${height}:r=${fps}`);
      } else {
        if (clip.kind === 'video') args.push('-noaccurate_seek', '-ss', String(clip.in));
        args.push(...inputOptions(media.get(clip.src).format?.format_name), '-threads', '2', '-i', resolve(root, clip.src));
      }
      const hasAudio = clip.kind === 'video' && media.get(clip.src).streams.some(stream => stream.codec_type === 'audio');
      if (!hasAudio) args.push('-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo');
      const videoFilters = [
        ...(clip.kind === 'image' ? [`select='eq(n,0)'`, 'loop=loop=-1:size=1:start=0', `setpts=N/(${fps}*TB)`] : []),
        // Sampling preroll first retains the source frame covering a sub-frame seek.
        ...(clip.kind === 'video' ? [`fps=${fps}:start_time=0`, 'trim=start=0', 'setpts=PTS-STARTPTS'] : []),
        `scale=${Math.ceil(width * effects.zoom / 2) * 2}:${Math.ceil(height * effects.zoom / 2) * 2}:force_original_aspect_ratio=increase`,
        `crop=${width}:${height}`, 'setsar=1', `fps=${fps}`,
        `tpad=stop_mode=clone:stop_duration=${1 / fps}`,
        ...(effects.brightness !== 0 || effects.contrast !== 1 || effects.saturation !== 1
          ? [`eq=brightness=${effects.brightness}:contrast=${effects.contrast}:saturation=${effects.saturation}`] : []),
        ...(effects.fadeIn > 0 ? [`fade=t=in:st=0:d=${effects.fadeIn}`] : []),
        ...(effects.fadeOut > 0 ? [`fade=t=out:st=${Math.max(0, duration - effects.fadeOut)}:d=${effects.fadeOut}`] : []),
      ];
      args.push(
        '-map', '0:v:0', '-map', hasAudio ? '0:a:0' : '1:a:0',
        '-vf', videoFilters.join(','),
        '-af', `atrim=start=0,aresample=48000:first_pts=0,aformat=channel_layouts=stereo,apad,atrim=duration=${duration},asetpts=PTS-STARTPTS,volume=${clip.volume ?? 1}`,
        '-frames:v', String(frameCount), '-t', String(duration),
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-threads', '2',
        '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
        '-n', `clip-${index}.mp4`,
      );
      await run(ffmpeg(), args, { cwd: workDir, signal });
    }
    const sha256 = await fileDigest(segment, signal);
    const bytes = (await stat(segment)).size;
    if (clipCache) clipCache.set(key, { file: segment, sha256 });
    segmentMetadata.push({ key, file: `clip-${index}.mp4`, sha256, bytes });
    await saveSegments(workDir, segmentMetadata);
    segments.push(`file 'clip-${index}.mp4'\nduration ${duration}`);
    await onProgress({ stage: 'clips', completed: index + 1, total: clips.length, cached: reused });
  }
  const duration = previousFrame / fps;
  await writeFile(join(workDir, 'segments.txt'), `${segments.join('\n')}\n`, { flag: 'wx' });

  const captions = [];
  if (timedCaptions.length) await prepareFont(workDir);
  for (const [index, caption] of timedCaptions.entries()) {
    await writeFile(join(workDir, `caption-${index}.txt`), caption.text, { flag: 'wx' });
    const y = { top: 'h*0.08', center: '(h-text_h)/2', bottom: 'h*0.88-text_h' }[caption.position];
    captions.push(`drawtext=fontfile=caption-font.ttf:textfile=caption-${index}.txt:expansion=none:fontsize=${caption.fontSize}:fontcolor=${caption.color}:x=(w-text_w)/2:y=${y}:box=1:boxcolor=black@0.55:boxborderw=12:enable='gte(t,${caption.start})*lt(t,${caption.end})'`);
  }
  const args = [...quiet, '-filter_complex_threads', '2', '-f', 'concat', '-safe', '1', '-i', 'segments.txt'];
  for (const track of project.audio) args.push(...localInput, '-i', resolve(root, track.src));
  for (const overlay of overlays) {
    if (overlay.kind === 'video') args.push('-noaccurate_seek', '-ss', String(overlay.in));
    args.push(...inputOptions(media.get(overlay.src).format?.format_name), '-threads', '2', '-i', resolve(root, overlay.src));
  }
  const audioFilters = [`[0:a]apad,atrim=duration=${duration},asetpts=PTS-STARTPTS[base]`];
  for (const [index, track] of project.audio.entries()) {
    const fades = [
      ...(track.fadeIn > 0 ? [`afade=t=in:st=0:d=${track.fadeIn}`] : []),
      ...(track.fadeOut > 0 ? [`afade=t=out:st=${Math.max(0, track.duration - track.fadeOut)}:d=${track.fadeOut}`] : []),
    ];
    audioFilters.push(`[${index + 1}:a:0]atrim=start=${track.in}:duration=${track.duration},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,volume=${track.volume},${fades.length ? `${fades.join(',')},` : ''}adelay=${Math.round(track.start * 1000)}:all=1[track${index}]`);
  }
  const tracks = project.audio.map((_, index) => `[track${index}]`).join('');
  audioFilters.push(`[base]${tracks}amix=inputs=${project.audio.length + 1}:duration=first:normalize=0:dropout_transition=0,alimiter=limit=0.95:latency=1,atrim=duration=${duration}[audio]`);
  const videoFilters = [];
  let picture = '[0:v]';
  for (const [index, overlay] of overlays.entries()) {
    const inputIndex = project.audio.length + index + 1;
    const { x, y, width: overlayWidth, height: overlayHeight } = overlay.rect;
    const overlayFilters = [
      ...(overlay.kind === 'image' ? [`select='eq(n,0)'`, 'loop=loop=-1:size=1:start=0', `setpts=N/(${fps}*TB)`] : []),
      `fps=${fps}:start_time=0`, `trim=start=0:duration=${overlay.duration}`,
      `tpad=stop_mode=clone:stop_duration=${1 / fps}`, 'settb=AVTB', `setpts=PTS-STARTPTS+${Math.round(overlay.start * 1000000)}`,
      'format=rgba', `scale=${overlayWidth}:${overlayHeight}:force_original_aspect_ratio=increase`,
      `crop=${overlayWidth}:${overlayHeight}`, 'setsar=1', `colorchannelmixer=aa=${overlay.opacity}`,
    ];
    videoFilters.push(`[${inputIndex}:v:0]${overlayFilters.join(',')}[overlay${index}]`);
    videoFilters.push(`${picture}[overlay${index}]overlay=x=${x}:y=${y}:eof_action=pass:repeatlast=0:format=auto:enable='gte(t,${overlay.start})*lt(t,${overlay.start + overlay.duration})'[layer${index}]`);
    picture = `[layer${index}]`;
  }
  videoFilters.push(`${picture}${captions.length ? captions.join(',') : 'null'}[video]`);
  await writeFile(join(workDir, 'compose-filter.txt'), [...videoFilters, ...audioFilters].join(';'), { flag: 'wx' });
  args.push('-/filter_complex', 'compose-filter.txt', '-map', '[video]', '-map', '[audio]');
  args.push(
    '-t', String(duration), '-frames:v', String(previousFrame), '-r', String(fps),
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-threads', '2',
    '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2', '-movflags', '+faststart', '-n', 'render.mp4',
  );
  await onProgress({ stage: 'compose', completed: 0, total: 1 });
  await run(ffmpeg(), args, { cwd: workDir, signal });
  await onProgress({ stage: 'compose', completed: 1, total: 1 });
  return { file: join(workDir, 'render.mp4'), duration, width, height, fps, cache };
}
