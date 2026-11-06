import { ProjectError } from './project.mjs';

function invalid(message) {
  throw new ProjectError('INVALID_WORDS', message);
}

export function groupWordCaptions(words, maxWords = 4) {
  if (!Number.isInteger(maxWords) || maxWords < 1 || maxWords > 12) {
    invalid('Caption group size must be an integer from 1 through 12');
  }
  if (!Array.isArray(words) || words.length > 2000) invalid('Expected an array of at most 2000 timed words');
  const ids = new Set();
  let previousEnd = 0;
  for (const [index, word] of words.entries()) {
    if (!word || typeof word !== 'object' || Array.isArray(word)
        || ![Object.prototype, null].includes(Object.getPrototypeOf(word))
        || Object.keys(word).some((key) => !['id', 'text', 'start', 'end'].includes(key))
        || typeof word.id !== 'string' || !/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(word.id)
        || ids.has(word.id)
        || typeof word.text !== 'string' || !word.text.trim() || word.text.length > 200 || word.text.includes('\0')
        || !Number.isFinite(word.start) || !Number.isFinite(word.end)
        || word.start < previousEnd || word.end <= word.start || word.end > 600) {
      invalid(`Invalid timed word at index ${index}: use unique IDs, nonempty text, and chronological, non-overlapping timestamps within 600 seconds`);
    }
    ids.add(word.id);
    previousEnd = word.end;
  }
  const captions = [];
  let group;
  let count = 0;
  let length = 0;
  for (const [index, word] of words.entries()) {
    const gap = index === 0 ? 0 : word.start - words[index - 1].end;
    if (!group || count === maxWords || gap > 0.6 + 1e-9 || length + 1 + word.text.length > 1000) {
      if (captions.length === 200) invalid('The supplied timings require more than 200 captions; choose a larger group size or split the production');
      group = { fromWord: word.id, toWord: word.id };
      captions.push(group);
      count = 0;
      length = 0;
    }
    group.toWord = word.id;
    length += (count === 0 ? 0 : 1) + word.text.length;
    count += 1;
  }
  return captions;
}
