import { countBatch } from './counter.js';

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== 'GPT_ASTRA_COUNT_TOKENS') return false;
  try {
    if (sender.id !== chrome.runtime.id) throw new Error('Invalid sender');
    sendResponse({ ok: true, counts: countBatch(message.texts) });
  } catch (error) {
    sendResponse({ ok: false, error: error.message });
  }
  return false;
});
