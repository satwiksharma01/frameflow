import { constants } from 'node:fs';
import { copyFile, mkdir, stat, writeFile } from 'node:fs/promises';
import { basename, dirname, extname, join, resolve } from 'node:path';
import { validateProject } from './project.mjs';
import { ffmpegPath, fileDigest, freshWorkDir, localInput, mediaError, runMedia, sourceMetadata } from './media-process.mjs';

function threshold(value) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1) {
    throw mediaError('INVALID_ARGUMENT', 'sceneThreshold must be a finite number from 0 through 1.');
  }
}

async function extractFrame(source, video, frame, requestedTime, duration, fps, signal) {
  // Seeking beyond the last decoded frame can exit successfully without creating an image.
  const bounded = Math.min(requestedTime, Math.max(0, duration - 1 / fps));
  for (const time of new Set([bounded, 0])) {
    await runMedia(ffmpegPath(), [
      '-v', 'error', '-nostdin', '-ss', String(time), ...localInput, '-i', source,
      '-map', `0:${video.index}`, '-frames:v', '1', '-vf', 'scale=480:480:force_original_aspect_ratio=decrease,pad=480:480:(ow-iw)/2:(oh-ih)/2',
      '-threads', '1', '-n', frame,
    ], { signal });
    try {
      const info = await stat(frame);
      if (!info.isFile() || info.size === 0) throw mediaError('INVALID_MEDIA', 'Video decoding did not produce a usable representative image.');
      return time;
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }
  throw mediaError('INVALID_MEDIA', 'Video has no decodable representative frame, including at its beginning.');
}

export async function inspectMedia(file, { workDir, sceneThreshold = 0.3, focusOpening = false, signal } = {}) {
  threshold(sceneThreshold);
  if (typeof focusOpening !== 'boolean') throw mediaError('INVALID_ARGUMENT', 'focusOpening must be a boolean.');
  const directory = await freshWorkDir(workDir);
  const { source, metadata, video, audio, duration, fps } = await sourceMetadata(file, signal);
  const report = {
    source, sha256: await fileDigest(source, signal), duration,
    width: video?.width ?? null, height: video?.height ?? null, fps,
    sourceFrameRate: video ? String(video.avg_frame_rate && video.avg_frame_rate !== '0/0' ? video.avg_frame_rate : video.r_frame_rate) : null,
    hasVideo: Boolean(video), hasAudio: Boolean(audio), scenes: [], frames: [], frameTimes: [], frameRequestedTimes: [], contactSheet: null,
    sceneThreshold, sceneLimitReached: false, frameSampling: focusOpening ? 'opening-and-representative' : 'representative',
  };
  if (video) {
    const scan = await runMedia(ffmpegPath(), [
      '-hide_banner', '-loglevel', 'info', '-nostdin', ...localInput, '-i', source,
      '-map', `0:${video.index}`, '-an', '-vf', `select='gt(scene,${sceneThreshold})',showinfo`,
      '-frames:v', '100', '-fps_mode', 'vfr', '-f', 'null', '-',
    ], { signal });
    const measured = [...scan.stderr.matchAll(/pts_time:([0-9]+(?:\.[0-9]+)?)/g)].map(match => Number(match[1]));
    report.scenes = [...new Set(measured.filter(time => time > 0 && time < duration))].sort((a, b) => a - b).slice(0, 99);
    report.sceneLimitReached = measured.length >= 100;
    const boundaries = [0, ...report.scenes, duration];
    const count = Math.min(12, Math.max(boundaries.length - 1, Math.ceil(duration / 2)));
    const representative = count === boundaries.length - 1
      ? boundaries.slice(0, -1).map((start, index) => (start + boundaries[index + 1]) / 2)
      : Array.from({ length: count }, (_, index) => duration * (index + 0.5) / count);
    const opening = [0, 0.5, 1, 2].filter(time => time < duration);
    const remaining = 12 - opening.length;
    const spread = representative.length <= remaining ? representative
      : Array.from({ length: remaining }, (_, index) => representative[Math.round(index * (representative.length - 1) / (remaining - 1))]);
    const times = focusOpening ? [...new Set(opening.concat(spread))].sort((a, b) => a - b) : representative;
    for (const [index, time] of times.entries()) {
      const frame = join(directory, `frame-${String(index).padStart(2, '0')}.png`);
      const selectedTime = await extractFrame(source, video, frame, time, duration, fps, signal);
      report.frames.push(frame);
      report.frameTimes.push(selectedTime);
      report.frameRequestedTimes.push(time);
    }
    const columns = Math.min(times.length, 4);
    report.contactSheet = join(directory, 'contact-sheet.png');
    await runMedia(ffmpegPath(), [
      '-v', 'error', '-nostdin', '-f', 'image2', '-start_number', '0', '-i', 'frame-%02d.png',
      '-frames:v', '1', '-vf', `tile=${columns}x${Math.ceil(times.length / columns)}:padding=8:margin=8`,
      '-threads', '1', '-n', 'contact-sheet.png',
    ], { cwd: directory, signal });
  }
  await writeFile(join(directory, 'metadata.json'), JSON.stringify(metadata, null, 2) + '\n', { flag: 'wx' });
  await writeFile(join(directory, 'report.json'), JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
  return report;
}

export async function reconstructMedia(file, directory, { sceneThreshold = 0.3, signal } = {}) {
  threshold(sceneThreshold);
  if (typeof directory !== 'string' || !directory.trim()) throw mediaError('INVALID_ARGUMENT', 'A new reconstruction directory is required.');
  const info = await sourceMetadata(file, signal);
  if (!info.video) throw mediaError('INVALID_MEDIA', 'Reconstruction requires a local video with a usable picture stream.');
  const target = resolve(directory);
  await mkdir(dirname(target), { recursive: true });
  try { await mkdir(target); } catch (error) {
    if (error.code === 'EEXIST') throw mediaError('OUTPUT_EXISTS', `Reconstruction directory already exists: ${target}`);
    throw error;
  }
  const assets = join(target, 'assets');
  const inspection = join(target, 'inspection');
  await mkdir(assets);
  await mkdir(inspection);
  const suffix = extname(info.source);
  const asset = `reference${/^\.[a-zA-Z0-9]{1,10}$/.test(suffix) ? suffix : '.media'}`;
  await copyFile(info.source, join(assets, asset), constants.COPYFILE_EXCL);
  const measured = await inspectMedia(join(assets, asset), { workDir: inspection, sceneThreshold, signal });
  const fps = Math.max(1, Math.min(60, Math.round(measured.fps)));
  const totalFrames = Math.floor(measured.duration * fps + 0.000001);
  if (totalFrames < 1) throw mediaError('INVALID_MEDIA', 'The reference is shorter than one output frame.');
  const frames = [0];
  for (const cut of measured.scenes) {
    const frame = Math.round(cut * fps);
    if (frame > frames.at(-1) && frame < totalFrames) frames.push(frame);
  }
  frames.push(totalFrames);
  const scale = Math.min(1, 3840 / Math.max(measured.width, measured.height));
  const project = validateProject({
    version: 1, title: basename(info.source).slice(0, 200),
    canvas: { width: Math.max(64, Math.floor(measured.width * scale / 2) * 2), height: Math.max(64, Math.floor(measured.height * scale / 2) * 2), fps },
    clips: frames.slice(0, -1).map((frame, index) => ({
      id: `shot${index + 1}`, kind: 'video', src: `assets/${asset}`, in: frame / fps,
      duration: (frames[index + 1] - frame) / fps, volume: 1,
    })),
  });
  const projectPath = join(target, 'project.json');
  await writeFile(projectPath, JSON.stringify(project, null, 2) + '\n', { flag: 'wx' });
  return { project: projectPath, report: join(inspection, 'report.json') };
}
