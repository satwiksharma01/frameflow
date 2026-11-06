import assert from 'node:assert/strict';
import test from 'node:test';
import { groupWordCaptions } from '../src/captions.mjs';

function transcript(count = 9) {
  return Array.from({ length: count }, (_, index) => ({
    id: `w${index}`, text: `word${index}`, start: index * 0.25, end: index * 0.25 + 0.2,
  }));
}

test('groups default sets of four without freezing text or timestamps', () => {
  const words = transcript();
  assert.deepEqual(groupWordCaptions(words), [
    { fromWord: 'w0', toWord: 'w3' },
    { fromWord: 'w4', toWord: 'w7' },
    { fromWord: 'w8', toWord: 'w8' },
  ]);
  assert.deepEqual(groupWordCaptions([]), []);
  assert.deepEqual(words, transcript());
});

test('starts a new group after a gap greater than 0.6 seconds', () => {
  const words = [
    { id: 'a', text: 'First', start: 0, end: 0.2 },
    { id: 'b', text: 'Second', start: 0.8, end: 1 },
    { id: 'c', text: 'Third', start: 1.61, end: 2 },
  ];
  assert.deepEqual(groupWordCaptions(words), [{ fromWord: 'a', toWord: 'b' }, { fromWord: 'c', toWord: 'c' }]);
});

test('validates group size and word input rather than truncating or returning broken anchors', () => {
  for (const size of [0, 13, 1.5, NaN, '4', null]) {
    assert.throws(() => groupWordCaptions(transcript(), size), { code: 'INVALID_WORDS' });
  }
  for (const words of [null, {}, [{ id: 'a' }], [transcript()[1], transcript()[0]],
    [transcript()[0], transcript()[0]], [{ ...transcript()[0], end: Infinity }]]) {
    assert.throws(() => groupWordCaptions(words), { code: 'INVALID_WORDS' });
  }
  assert.throws(() => groupWordCaptions(transcript(201), 1), { code: 'INVALID_WORDS' });
  assert.throws(() => groupWordCaptions(transcript(2001), 12), { code: 'INVALID_WORDS' });
  assert.equal(groupWordCaptions(transcript(200), 1).length, 200);
});

test('starts a fresh group before derived wording would exceed 1000 characters', () => {
  const words = transcript(8).map((word) => ({ ...word, text: 'x'.repeat(200) }));
  assert.deepEqual(groupWordCaptions(words, 12), [
    { fromWord: 'w0', toWord: 'w3' }, { fromWord: 'w4', toWord: 'w7' },
  ]);
});
