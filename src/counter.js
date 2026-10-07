import { Tiktoken } from 'js-tiktoken/lite';
import ranks from 'js-tiktoken/ranks/o200k_base';

let encoder;

export function countTokens(text) {
  if (typeof text !== 'string') throw new TypeError('Expected text');
  encoder ??= new Tiktoken(ranks);
  // User-written special-token-looking strings are ordinary message text.
  return encoder.encode(text, [], []).length;
}

export function countBatch(texts) {
  if (!Array.isArray(texts) || texts.length > 1000 ||
      texts.some(text => typeof text !== 'string') ||
      texts.reduce((sum, text) => sum + text.length, 0) > 2_000_000) {
    throw new Error('ข้อความมากเกินขีดจำกัดตัวนับ');
  }
  return texts.map(countTokens);
}
