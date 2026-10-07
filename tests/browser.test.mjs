import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from 'playwright-core';
import { mkdtemp, rm, mkdir, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { countTokens } from '../src/counter.js';

let context;
let page;
let profile;
const storedSettings = {};
const settingsKey = 'gptAstraTokenHudSettings';
const fixture = `<!doctype html><html lang="th"><head><meta charset="utf-8"><title>Token HUD fixture</title>
<style>body{background:#202123;color:#ececec;font:16px system-ui;padding:50px}main{max-width:620px}article{background:#2b2d33;border-radius:14px;padding:20px;margin:16px 0}pre{white-space:pre-wrap}</style>
</head><body><main><h1>GPT Astra — conversation fixture</h1>
<article data-message-author-role="user"><div data-message-content>hello world</div></article>
<article data-message-author-role="assistant"><div data-message-content>สวัสดี</div><button>Copy message</button></article>
<article data-message-author-role="assistant" hidden><div data-message-content>hidden branch must not count</div></article>
<article data-message-author-role="assistant" style="display:none"><div data-message-content>CSS hidden branch must not count</div></article>
</main></body></html>`;

before(async () => {
  profile = await mkdtemp(path.join(tmpdir(), 'astra-browser-'));
  const contentScript = await readFile('dist/content.js', 'utf8');
  const backgroundScript = await readFile('dist/background.js', 'utf8');
  context = await chromium.launchPersistentContext(profile, {
    executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium',
    headless: true,
    viewport: { width: 1100, height: 760 },
    args: ['--no-sandbox'],
  });
  // The cloud browser disables unpacked extensions by policy. This explicitly
  // tests the built scripts through a minimal Chrome-API harness, not native
  // manifest registration or a real ChatGPT account.
  await context.exposeBinding('astraTestStorage', (_, operation, value) => {
    if (operation === 'get') return structuredClone(storedSettings);
    Object.assign(storedSettings, structuredClone(value));
  });
  await context.route('https://chatgpt.com/**', route => {
    if (route.request().url().endsWith('/astra-test-worker.js')) {
      const bridge = `self.chrome={runtime:{id:'astra-test',onMessage:{addListener(listener){self.onmessage=e=>listener(e.data.message,{id:'astra-test'},result=>self.postMessage({id:e.data.id,result}));}}}};`;
      return route.fulfill({ contentType: 'application/javascript', body: bridge + backgroundScript });
    }
    return route.fulfill({ contentType: 'text/html', body: fixture });
  });
  await context.addInitScript({ content: `
    const tokenizer = new Worker('/astra-test-worker.js');
    const pending = new Map();
    let requestId = 0;
    const storageListeners = [];
    tokenizer.onmessage = event => {
      pending.get(event.data.id)?.(event.data.result);
      pending.delete(event.data.id);
    };
    window.chrome = {
      runtime: { sendMessage(message) {
        return new Promise(resolve => {
          const id = ++requestId;
          pending.set(id, resolve);
          tokenizer.postMessage({ id, message });
        });
      } },
      storage: {
        local: {
          get() { return window.astraTestStorage('get'); },
          async set(value) {
            const old = await window.astraTestStorage('get');
            await window.astraTestStorage('set', value);
            const changes = Object.fromEntries(Object.entries(value).map(([key, newValue]) => [key, {oldValue:old[key],newValue}]));
            storageListeners.forEach(listener => listener(changes, 'local'));
          }
        },
        onChanged: { addListener(listener) { storageListeners.push(listener); } }
      }
    };
    window.addEventListener('DOMContentLoaded', () => { ${contentScript} });
  ` });
  page = await context.newPage();
  await page.goto('https://chatgpt.com/c/astra-test');
  await page.locator('#gpt-astra-token-hud').waitFor();
}, { timeout: 30_000 });

after(async () => {
  await context?.close();
  if (profile) await rm(profile, { recursive: true, force: true });
});

async function waitUsed(expected, messages = null) {
  await page.waitForFunction(({ expected, messages }) => {
    const root = document.querySelector('#gpt-astra-token-hud')?.shadowRoot;
    const usage = root?.querySelector('.usage')?.textContent;
    return usage?.includes(`ใช้ไปประมาณ ${new Intl.NumberFormat('th-TH').format(expected)} โทเคน`) &&
      (messages === null || usage.includes(`· ${messages} ข้อความ`));
  }, { expected, messages }, { timeout: 15_000 });
}

async function setBudget(budget) {
  await page.evaluate(async ({ key, budget }) => chrome.storage.local.set({ [key]: { budget } }), { key: settingsKey, budget });
}

test('built scripts count visible English/Thai and ignore toolbars and hidden branches', async () => {
  await waitUsed(6);
  assert.equal(await page.locator('#gpt-astra-token-hud .balance').textContent(), 'ยังไม่ทราบ');
  assert.equal(await page.locator('#gpt-astra-token-hud .meter').getAttribute('aria-valuenow'), null);
  assert.match(await page.locator('#gpt-astra-token-hud .footnote').textContent(), /ไม่ใช่โควตาบัญชี GPT/);
});

test('budget settings and streaming replace prior counts rather than double-counting', async () => {
  await page.getByRole('button', { name: 'ตั้งงบโทเคน' }).click();
  await page.locator('#gpt-astra-token-hud input').fill('100');
  await page.getByRole('button', { name: 'บันทึกงบ', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#gpt-astra-token-hud').shadowRoot.querySelector('.balance').textContent === '94');
  await page.evaluate(() => document.querySelector('[data-message-author-role="assistant"] [data-message-content]').textContent = 'hello');
  await waitUsed(3);
  await page.evaluate(() => document.querySelector('[data-message-author-role="assistant"] [data-message-content]').textContent = 'hello world');
  await waitUsed(4);
  assert.equal(await page.locator('#gpt-astra-token-hud .balance').textContent(), '96');
});

test('edits, code, removal and local over-budget state reflect current rendered text', async () => {
  const code = 'const x = 1;';
  await page.evaluate(code => {
    const root = document.querySelector('[data-message-author-role="assistant"] [data-message-content]');
    root.replaceChildren(Object.assign(document.createElement('pre'), { textContent: code }));
  }, code);
  await waitUsed(2 + countTokens(code));
  await page.evaluate(() => document.querySelector('[data-message-author-role="user"]').remove());
  await waitUsed(countTokens(code));
  await setBudget(1);
  await page.waitForFunction(() => document.querySelector('#gpt-astra-token-hud').shadowRoot.querySelector('.balance').textContent === '0');
  assert.equal(await page.locator('#gpt-astra-token-hud .meter').getAttribute('data-tone'), 'danger');
});

test('SPA navigation clears old totals and unsupported pages show unknown', async () => {
  await page.evaluate(() => {
    document.querySelector('main').replaceChildren(Object.assign(document.createElement('h1'), { textContent: 'Next conversation' }));
    history.pushState({}, '', '/codex/tasks/next');
  });
  await page.waitForFunction(() => document.querySelector('#gpt-astra-token-hud').shadowRoot.querySelector('.balance').textContent === 'ยังไม่ทราบ');
  assert.equal(await page.locator('#gpt-astra-token-hud .meter').getAttribute('aria-valuenow'), null);
  assert.match(await page.locator('#gpt-astra-token-hud .note').textContent(), /ยังไม่เปิดเผย/);
});

test('settings persist across reload; extension stores settings without chat text', async () => {
  await setBudget(1000);
  await page.goto('https://chatgpt.com/c/astra-test-2');
  await waitUsed(6);
  assert.equal(await page.locator('#gpt-astra-token-hud .balance').textContent(), '994');
  const stored = await page.evaluate(() => chrome.storage.local.get(null));
  assert.deepEqual(stored, { [settingsKey]: { budget: 1000 } });
});

test('ChatGPT markdown-shaped messages exclude code controls and CSS-hidden display-contents branches', async () => {
  await page.evaluate(() => {
    document.querySelector('main').innerHTML = `<article data-message-author-role="assistant"><div class="markdown"><div><div>javascript<button>Copy code</button></div><pre><code>const x = 1;</code></pre></div></div><footer>Good response</footer></article><section style="display:none"><article style="display:contents" data-message-author-role="assistant">hidden</article></section>`;
  });
  await waitUsed(countTokens('const x = 1;'), 1);
  assert.match(await page.locator('#gpt-astra-token-hud .usage').textContent(), /1 ข้อความ/);
});

test('counter failures clear stale balances and recover after a valid update', async () => {
  await page.evaluate(() => document.querySelector('code').textContent = 'a'.repeat(2_000_001));
  await page.waitForFunction(() => document.querySelector('#gpt-astra-token-hud').shadowRoot.querySelector('.note').textContent.includes('มากเกินขีดจำกัด'));
  assert.equal(await page.locator('#gpt-astra-token-hud .balance').textContent(), 'ยังไม่ทราบ');
  await page.evaluate(() => document.querySelector('code').textContent = 'hello');
  await waitUsed(1, 1);
});

test('HUD is top-right, collapses and recovers if host is replaced by page navigation', async () => {
  await page.goto('https://chatgpt.com/c/astra-test-3');
  await waitUsed(6);
  const bounds = await page.locator('#gpt-astra-token-hud').boundingBox();
  assert.equal(bounds.y, 16);
  assert.ok(Math.abs(bounds.x + bounds.width - 1084) < 1);
  await page.getByRole('button', { name: 'ย่อแถบโทเคน' }).click();
  assert.equal(await page.locator('#gpt-astra-token-hud .body').isVisible(), false);
  await page.getByRole('button', { name: 'ขยายแถบโทเคน' }).click();
  await page.evaluate(() => document.querySelector('#gpt-astra-token-hud').remove());
  await page.locator('#gpt-astra-token-hud').waitFor();
  await waitUsed(6);
  await setBudget(10);
  await page.waitForFunction(() => document.querySelector('#gpt-astra-token-hud').shadowRoot.querySelector('.balance').textContent === '4');
  await page.waitForFunction(() => {
    const root = document.querySelector('#gpt-astra-token-hud').shadowRoot;
    const meter = root.querySelector('.meter');
    const ratio = root.querySelector('.fill').getBoundingClientRect().width / meter.clientWidth;
    return meter.dataset.tone === 'warning' && Math.abs(ratio - 0.4) < 0.005;
  });
  await mkdir('artifacts', { recursive: true });
  await page.screenshot({ path: 'artifacts/token-hud.png' });
});
