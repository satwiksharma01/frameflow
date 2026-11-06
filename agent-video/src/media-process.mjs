import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { lstat, readdir, realpath, stat } from 'node:fs/promises';
import { resolve } from 'node:path';
import { probeMedia, SUPPORTED_INPUT_FORMATS } from './render.mjs';

export const ffmpegPath = () => process.env.FFMPEG_PATH || 'ffmpeg';
export const localInput = ['-protocol_whitelist', 'file,pipe', '-format_whitelist', SUPPORTED_INPUT_FORMATS];
export const mediaError = (code, message) => Object.assign(new Error(message), { code });

export function runMedia(executable, args, { cwd, signal, timeout = 30 * 60 * 1000 } = {}) {
  if (signal?.aborted) return Promise.reject(mediaError('CANCELLED', 'Media processing was cancelled.'));
  return new Promise((resolveResult, reject) => {
    let stdout = '';
    let stderr = '';
    let processError;
    let timedOut = false;
    const child = spawn(executable, args, { cwd, signal, shell: false, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    const deadline = setTimeout(() => { timedOut = true; child.kill(); }, timeout);
    deadline.unref();
    child.stdout.setEncoding('utf8').on('data', data => { stdout = (stdout + data).slice(-2 * 1024 * 1024); });
    child.stderr.setEncoding('utf8').on('data', data => { stderr = (stderr + data).slice(-2 * 1024 * 1024); });
    child.on('error', error => { processError = error; });
    child.on('close', code => {
      clearTimeout(deadline);
      if (signal?.aborted) return reject(mediaError('CANCELLED', 'Media processing was cancelled.'));
      if (timedOut) return reject(mediaError('TOOL_TIMEOUT', `${executable} exceeded the media processing deadline.`));
      if (processError) return reject(mediaError('TOOL_UNAVAILABLE', `Cannot start ${executable}: ${processError.message}`));
      if (code !== 0) return reject(mediaError('TOOL_FAILED', `${executable} failed (exit ${code}): ${stderr.slice(-16384).trim()}`));
      resolveResult({ stdout, stderr });
    });
  });
}

export async function freshWorkDir(workDir) {
  if (typeof workDir !== 'string' || !workDir.trim()) throw mediaError('INVALID_ARGUMENT', 'A fresh workDir directory is required.');
  const directory = resolve(workDir);
  if (!(await lstat(directory)).isDirectory() || (await readdir(directory)).length) {
    throw mediaError('OUTPUT_EXISTS', `Media work directory must be an empty, regular directory: ${directory}`);
  }
  return directory;
}

export async function fileDigest(file, signal) {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(file, { signal })) hash.update(chunk);
  return hash.digest('hex');
}

export async function sourceMetadata(file, signal) {
  if (signal?.aborted) throw mediaError('CANCELLED', 'Media processing was cancelled.');
  let source;
  try {
    if (typeof file !== 'string' || !file.trim()) throw new Error('expected a local file path');
    source = await realpath(resolve(file));
    if (!(await stat(source)).isFile()) throw new Error('not a regular file');
  } catch (error) { throw mediaError('INVALID_MEDIA', `Cannot read local media: ${error.message}`); }
  const metadata = await probeMedia(source, { signal });
  const video = metadata.streams.find(stream => stream.codec_type === 'video' && !stream.disposition?.attached_pic);
  const audio = metadata.streams.find(stream => stream.codec_type === 'audio');
  const duration = Number(video?.duration ?? metadata.format?.duration ?? audio?.duration);
  if (!Number.isFinite(duration) || duration <= 0 || duration > 600 || Number(metadata.format?.duration) > 600) {
    throw mediaError('INVALID_MEDIA', 'Media must have a known duration greater than zero and at most 600 seconds.');
  }
  if (!video && !audio) throw mediaError('INVALID_MEDIA', 'Media has no usable video or audio stream.');
  let fps = null;
  if (video) {
    for (const value of [video.avg_frame_rate, video.r_frame_rate]) {
      const rate = String(value).split('/').map(Number);
      const candidate = rate.length === 2 ? rate[0] / rate[1] : rate[0];
      if (Number.isFinite(candidate) && candidate > 0) { fps = candidate; break; }
    }
    if (!Number.isFinite(fps) || fps <= 0 || !Number.isInteger(video.width) || !Number.isInteger(video.height)
        || video.width <= 0 || video.height <= 0) throw mediaError('INVALID_MEDIA', 'Video dimensions or frame rate are unavailable.');
  }
  return { source, metadata, video, audio, duration, fps };
}
