import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import test from 'node:test';
import { parseWhisperJson, transcribeMedia } from '../src/transcribe.mjs';

function recognized() {
  return {
    result: { language: 'en' },
    transcription: [
      { text: ' ', offsets: { from: 0, to: 100 }, tokens: [] },
      { text: ' Hello,', offsets: { from: 100, to: 500 }, tokens: [{ text: ' Hello', id: 2425 }] },
      { text: ' world!', offsets: { from: 600, to: 1000 }, tokens: [{ text: ' world', id: 1002 }] },
      { text: '[_EOT_]', tokens: [{ text: '[_EOT_]', id: 50256 }] },
    ],
  };
}

test('uses real whisper.cpp word segment offsets in milliseconds and excludes blank/special output', () => {
  const parsed = parseWhisperJson(recognized(), 2);
  assert.deepEqual(parsed.words, [
    { id: 'w1', text: 'Hello,', start: 0.1, end: 0.5 },
    { id: 'w2', text: 'world!', start: 0.6, end: 1 },
  ]);
  assert.equal(parsed.text, 'Hello, world!');
  assert.equal(parsed.language, 'en');
});

test('rejects unsegmented text, missing/invalid timing and malformed engine JSON', () => {
  for (const value of [null, {}, { transcription: 'wrong' }]) {
    assert.throws(() => parseWhisperJson(value, 2), { code: 'INVALID_TRANSCRIPT' });
  }
  for (const patch of [
    { text: 'two words' }, { offsets: undefined }, { offsets: { from: -1, to: 500 } },
    { offsets: { from: 100, to: 100 } }, { offsets: { from: 100, to: 3000 } },
    { offsets: { from: '100', to: 500 } },
  ]) {
    const data = recognized();
    Object.assign(data.transcription[1], patch);
    assert.throws(() => parseWhisperJson(data, 2), { code: 'INVALID_TRANSCRIPT' });
  }
  const overlap = recognized();
  overlap.transcription[2].offsets.from = 300;
  assert.throws(() => parseWhisperJson(overlap, 2), { code: 'INVALID_TRANSCRIPT' });
});

test('missing local transcription prerequisites are reported without inventing a transcript', async t => {
  const root = await mkdtemp(join(tmpdir(), 'agent-video-transcribe-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const workDir = join(root, 'work');
  await mkdir(workDir);
  const previous = process.env.WHISPER_CPP_PATH;
  delete process.env.WHISPER_CPP_PATH;
  try {
    await assert.rejects(transcribeMedia(join(root, 'audio.wav'), { workDir }), error => error.code === 'TRANSCRIBER_UNAVAILABLE' && /WHISPER_CPP_PATH/.test(error.message));
  } finally {
    if (previous !== undefined) process.env.WHISPER_CPP_PATH = previous;
  }
});
