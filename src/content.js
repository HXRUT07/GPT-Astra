import { makeSnapshot, parseBudget } from './core.js';
import { collectMessages } from './messages.js';
import { mountHud } from './hud.js';

const SETTINGS_KEY = 'gptAstraTokenHudSettings';
const HOST_ID = 'gpt-astra-token-hud';

async function start() {
  if (document.getElementById(HOST_ID)) return;
  let budget = null;
  let storageError = '';
  try {
    const stored = await chrome.storage.local.get(SETTINGS_KEY);
    budget = parseBudget(stored[SETTINGS_KEY]?.budget);
  } catch {
    storageError = 'อ่านการตั้งค่าไม่ได้ เปิดตั้งค่าเพื่อบันทึกงบใหม่';
  }

  let cache = new WeakMap();
  let lastRoute = location.pathname;
  let lastSignature = '';
  let timer;
  let busy = false;
  let dirty = false;
  const hud = mountHud({
    async onBudgetChange(value) {
      const next = parseBudget(value);
      await chrome.storage.local.set({ [SETTINGS_KEY]: { budget: next } });
      budget = next;
      storageError = '';
      lastSignature = '';
      schedule();
    },
  });
  hud.host.id = HOST_ID;
  hud.host.setAttribute('data-token-hud-root', '');
  hud.update(makeSnapshot({ budget, note: 'กำลังอ่านข้อความในหน้า' }));

  function schedule() {
    dirty = true;
    if (!timer && !busy) timer = setTimeout(refresh, 250);
  }

  async function refresh() {
    timer = undefined;
    if (busy) return;
    busy = true;
    dirty = false;
    const route = location.pathname;
    try {
      if (!hud.host.isConnected) document.documentElement.append(hud.host);
      if (route !== lastRoute) {
        cache = new WeakMap();
        lastSignature = '';
        lastRoute = route;
        hud.update(makeSnapshot({ budget, note: 'กำลังอ่านแชตใหม่' }));
      }
      const messages = collectMessages(document);
      const signature = JSON.stringify([route, budget, messages.map(({ role, text }) => [role, text])]);
      if (signature === lastSignature) return;
      if (messages.length === 0) {
        hud.update(makeSnapshot({
          budget,
          status: route.startsWith('/codex') ? 'unsupported' : 'waiting',
          note: storageError || (route.startsWith('/codex')
            ? 'หน้านี้ยังไม่เปิดเผยข้อความที่ตัวนับอ่านได้'
            : 'ยังไม่พบข้อความแชตที่อ่านได้'),
        }));
        lastSignature = signature;
        return;
      }
      const changed = messages.filter(message => cache.get(message.element)?.text !== message.text);
      if (changed.length) {
        const response = await chrome.runtime.sendMessage({
          type: 'GPT_ASTRA_COUNT_TOKENS',
          texts: changed.map(message => message.text),
        });
        if (!response?.ok || !Array.isArray(response.counts) || response.counts.length !== changed.length ||
            response.counts.some(count => !Number.isSafeInteger(count) || count < 0)) {
          throw new Error(response?.error || 'ตัวนับโทเคนยังไม่พร้อม');
        }
        if (location.pathname !== route) {
          dirty = true;
          return;
        }
        changed.forEach((message, index) => cache.set(message.element, {
          text: message.text,
          count: response.counts[index],
        }));
      }
      const used = messages.reduce((sum, message) => sum + cache.get(message.element).count, 0);
      hud.update(makeSnapshot({
        used,
        messages: messages.length,
        budget,
        note: storageError || 'นับเฉพาะข้อความที่โหลดในแชตนี้ ไม่รวมรูปภาพและบริบทที่ซ่อน',
      }));
      lastSignature = signature;
    } catch (error) {
      // Discard stale balances rather than keeping a seemingly valid number.
      hud.update(makeSnapshot({ budget, status: 'error', note: error.message }));
      lastSignature = '';
    } finally {
      busy = false;
      if (dirty) schedule();
    }
  }

  const observer = new MutationObserver(records => {
    if (records.some(record => record.target !== hud.host && !hud.host.contains(record.target))) schedule();
  });
  observer.observe(document.documentElement, {
    childList: true,
    characterData: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['data-message-author-role', 'hidden', 'aria-hidden', 'style', 'class'],
  });
  // Browser page lifecycle handles these timers. Keeping them attached also
  // restores monitoring when a document returns from the back/forward cache.
  setInterval(schedule, 1000);
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local' || !changes[SETTINGS_KEY]) return;
    try {
      budget = parseBudget(changes[SETTINGS_KEY].newValue?.budget);
      lastSignature = '';
      schedule();
    } catch {
      budget = null;
      storageError = 'งบที่บันทึกไว้ไม่ถูกต้อง กรุณาตั้งใหม่';
      lastSignature = '';
      schedule();
    }
  });
  schedule();
}

start().catch(error => console.warn('GPT Astra Token HUD could not start:', error.message));
