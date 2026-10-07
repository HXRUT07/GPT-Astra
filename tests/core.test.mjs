import test from 'node:test';
import assert from 'node:assert/strict';
import { countTokens, countBatch } from '../src/counter.js';
import { makeSnapshot, parseBudget, MAX_BUDGET } from '../src/core.js';

test('tokenizer counts English, Thai and code with o200k_base', () => {
  assert.equal(countTokens('hello'), 1);
  assert.equal(countTokens('hello world'), 2);
  assert.equal(countTokens('สวัสดี'), 4);
  assert.equal(countTokens('const x = 1;'), 6);
  assert.equal(countTokens(''), 0);
});

test('user text containing special-token markers is counted literally', () => {
  assert.equal(countTokens('<|endoftext|>'), 7);
  assert.ok(countTokens('👩🏽‍💻') > 0);
});

test('batch validation rejects unsupported payloads and bounded oversized input', () => {
  assert.deepEqual(countBatch(['hello', 'สวัสดี']), [1, 4]);
  assert.throws(() => countBatch(['hello', 5]));
  assert.throws(() => countBatch(Array(1001).fill('')));
  assert.throws(() => countBatch(['a'.repeat(2_000_001)]));
});

test('no configured budget never implies a remaining token balance', () => {
  const snapshot = makeSnapshot({ used: 125, messages: 2 });
  assert.equal(snapshot.used, 125);
  assert.equal(snapshot.budget, null);
  assert.equal(snapshot.remaining, null);
  assert.equal(snapshot.percent, null);
});

test('no readable messages never implies a full budget or a known zero usage', () => {
  const snapshot = makeSnapshot({ budget: 1000 });
  assert.equal(snapshot.used, null);
  assert.equal(snapshot.remaining, null);
  assert.equal(snapshot.percent, null);
  assert.equal(snapshot.updatedAt, null);
});

test('configured local budget reports the visible estimate and clamps overspending', () => {
  const normal = makeSnapshot({ budget: 1000, used: 250, messages: 2 });
  assert.equal(normal.remaining, 750);
  assert.equal(normal.percent, 75);
  const exceeded = makeSnapshot({ budget: 100, used: 125 });
  assert.equal(exceeded.used, 125);
  assert.equal(exceeded.remaining, 0);
  assert.equal(exceeded.percent, 0);
});

test('budget inputs preserve unknown, allow explicit bounds and reject invalid values', () => {
  for (const value of [null, undefined, '']) assert.equal(parseBudget(value), null);
  assert.equal(parseBudget('128000'), 128000);
  assert.equal(parseBudget(1), 1);
  assert.equal(parseBudget(MAX_BUDGET), MAX_BUDGET);
  for (const value of [0, -1, 1.5, MAX_BUDGET + 1, true, NaN, Infinity, '1e3', '0xFF', '10abc', ' ']) {
    assert.throws(() => parseBudget(value));
  }
});
