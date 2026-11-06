import { access, readFile, stat } from 'node:fs/promises';
import { constants } from 'node:fs';
import { join, resolve } from 'node:path';
import { ffmpegPath, freshWorkDir, localInput, mediaError, runMedia, sourceMetadata } from './media-process.mjs';

function invalid(message) { throw mediaError('INVALID_TRANSCRIPT', message); }

export function parseWhisperJson(value, duration) {
  if (!value || !Array.isArray(value.transcription) || value.transcription.length > 10000
      || !Number.isFinite(duration) || duration <= 0 || duration > 600) invalid('Expected full whisper.cpp JSON with a transcription array and a valid source duration.');
  const words = [];
  let previousEnd = 0;
  for (const [index, segment] of value.transcription.entries()) {
    if (!segment || typeof segment.text !== 'string' || segment.text.includes('\0')) invalid(`Malformed recognition segment ${index}.`);
    const text = segment.text.trim();
    if (!text || /^(?:\[_[^\]]+\]|\[BLANK_AUDIO\]|<\|[^>]+\|>)$/.test(text)) continue;
    if (text.length > 200 || /\s/u.test(text) || !Array.isArray(segment.tokens)) {
      invalid(`Recognition segment ${index} is not one word with full JSON metadata; use whisper-cli -ml 1 -sow -ojf.`);
    }
    const from = segment.offsets?.from;
    const to = segment.offsets?.to;
    if (!Number.isInteger(from) || !Number.isInteger(to) || from < 0 || to <= from
        || from / 1000 < previousEnd || to / 1000 > duration || words.length >= 2000) {
      invalid(`Recognition segment ${index} has invalid, overlapping, out-of-range, or excessive word timings.`);
    }
    words.push({ id: `w${words.length + 1}`, text, start: from / 1000, end: to / 1000 });
    previousEnd = to / 1000;
  }
  const language = value.result?.language;
  if (typeof language !== 'string' || !/^[a-z]{2,3}(?:-[a-z]{2,3})?$/.test(language)) invalid('Recognizer JSON has no valid detected language.');
  return { words, text: words.map(word => word.text).join(' '), language };
}

export async function transcribeMedia(file, { workDir, language = 'en', signal } = {}) {
  const executable = process.env.WHISPER_CPP_PATH;
  const model = process.env.WHISPER_CPP_MODEL;
  if (!executable || !model) throw mediaError('TRANSCRIBER_UNAVAILABLE', 'Local transcription requires WHISPER_CPP_PATH pointing to whisper-cli and WHISPER_CPP_MODEL pointing to an existing ggml model.');
  if (typeof language !== 'string' || !/^(?:auto|[a-z]{2,3}(?:-[a-z]{2,3})?)$/.test(language)) {
    throw mediaError('INVALID_ARGUMENT', 'language must be a lowercase language code, such as en, or auto.');
  }
  try {
    if (!(await stat(resolve(executable))).isFile() || !(await stat(resolve(model))).isFile()) throw new Error('expected executable and model files');
    await access(resolve(model), constants.R_OK);
  } catch (error) { throw mediaError('TRANSCRIBER_UNAVAILABLE', `Cannot use WHISPER_CPP_PATH/WHISPER_CPP_MODEL: ${error.message}`); }
  const directory = await freshWorkDir(workDir);
  const source = await sourceMetadata(file, signal);
  if (!source.audio) throw mediaError('INVALID_MEDIA', 'Transcription requires an audio stream.');
  const audio = join(directory, 'speech.wav');
  await runMedia(ffmpegPath(), [
    '-v', 'error', '-nostdin', ...localInput, '-i', source.source,
    '-map', `0:${source.audio.index}`, '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', '-n', audio,
  ], { signal });
  const prefix = join(directory, 'recognition');
  const raw = `${prefix}.json`;
  // Official whisper.cpp CLI: -ml 1 with -sow emits word segments; offsets in -ojf JSON are milliseconds.
  await runMedia(resolve(executable), ['-m', resolve(model), '-f', audio, '-l', language, '-ml', '1', '-sow', '-ojf', '-of', prefix], { cwd: directory, signal });
  let data;
  try {
    if ((await stat(raw)).size > 16 * 1024 * 1024) invalid('Recognizer output exceeds the 16 MiB limit.');
    data = JSON.parse(await readFile(raw, 'utf8'));
  } catch (error) {
    if (error.code === 'INVALID_TRANSCRIPT') throw error;
    invalid(`Cannot read full whisper.cpp JSON: ${error.message}`);
  }
  const parsed = parseWhisperJson(data, Number(source.audio.duration ?? source.metadata.format?.duration ?? source.duration));
  if (!parsed.words.length) throw mediaError('NO_SPEECH', 'The local recognizer returned no timed speech words. Raw recognition output was retained.');
  return { ...parsed, engine: 'whisper.cpp', audio, raw };
}
