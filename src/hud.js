const MAX_BUDGET = 10_000_000;
const numberFormat = new Intl.NumberFormat('th-TH');
let mountCount = 0;

const styles = `
  :host {
    all: initial;
    position: fixed;
    top: 16px;
    right: 16px;
    z-index: 2147483647;
    display: block;
    color-scheme: dark;
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 13px;
    font-weight: 400;
    line-height: 1.5;
    direction: ltr;
    text-align: left;
  }
  *, *::before, *::after { box-sizing: border-box; }
  [hidden] { display: none !important; }
  .card {
    width: min(296px, calc(100vw - 32px));
    overflow: hidden;
    border: 1px solid #343d52;
    border-radius: 16px;
    background: #111722;
    color: #f3f6fc;
    box-shadow: 0 12px 36px #0006, 0 1px 0 #ffffff08 inset;
  }
  .header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 11px 12px;
    border-bottom: 1px solid #ffffff0c;
  }
  .mark {
    display: grid;
    width: 25px;
    height: 25px;
    flex: 0 0 auto;
    place-items: center;
    border: 1px solid #43c8a85c;
    border-radius: 8px;
    background: #173a34;
    color: #78edc9;
    font-size: 16px;
    font-weight: 800;
  }
  .heading { flex: 1; min-width: 0; }
  .title {
    margin: 0;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: .1em;
    white-space: nowrap;
  }
  .subtitle { margin: 0; color: #b7c2d5; font-size: 11px; }
  button, input { font: inherit; }
  button {
    border: 0;
    border-radius: 7px;
    cursor: pointer;
    transition: background .12s ease, border-color .12s ease;
  }
  button:focus-visible, input:focus-visible {
    outline: 2px solid #83e6c9;
    outline-offset: 3px;
  }
  .icon-button {
    display: grid;
    width: 28px;
    height: 28px;
    flex: 0 0 auto;
    place-items: center;
    padding: 0;
    background: transparent;
    color: #b7c2d5;
    font-size: 17px;
  }
  .icon-button:hover { background: #ffffff12; color: #fff; }
  .body { padding: 13px 14px 12px; }
  .balance-label { margin: 0 0 2px; color: #c7d1e3; font-size: 12px; }
  .balance {
    margin: 0;
    color: #f3f6fc;
    font-size: 26px;
    font-weight: 750;
    font-variant-numeric: tabular-nums;
    letter-spacing: -.025em;
    line-height: 1.3;
    overflow-wrap: anywhere;
  }
  .balance.unknown { font-size: 21px; }
  .capacity { margin: 3px 0 10px; color: #a7b4cc; font-size: 11px; }
  .meter {
    height: 11px;
    overflow: hidden;
    border: 1px solid #ffffff0d;
    border-radius: 5px;
    background: #283346;
  }
  .fill {
    width: 0;
    height: 100%;
    border-radius: 3px;
    background: #6ee7b7;
    box-shadow: 0 0 10px #6ee7b73d inset;
    transition: width .24s ease, background .18s ease;
  }
  .meter[data-tone="warning"] .fill { background: #f4c55a; }
  .meter[data-tone="danger"] .fill { background: #fb7884; }
  .meter[data-tone="unknown"] {
    background: repeating-linear-gradient(135deg, #253043 0 7px, #303c50 7px 14px);
  }
  .meter[data-tone="unknown"] .fill { display: none; }
  .usage {
    margin: 8px 0 0;
    color: #b7c2d5;
    font-size: 11px;
    font-variant-numeric: tabular-nums;
  }
  .note { margin: 8px 0 0; color: #c7d1e3; font-size: 11px; overflow-wrap: anywhere; }
  .footnote {
    margin: 10px 0 0;
    padding-top: 9px;
    border-top: 1px solid #ffffff0b;
    color: #a8b6cc;
    font-size: 10px;
    line-height: 1.5;
  }
  .time { margin: 3px 0 0; color: #8f9eb6; font-size: 10px; }
  .compact {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 9px 12px;
    color: #d9e3f4;
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }
  .compact-dot { width: 7px; height: 7px; border-radius: 50%; background: #a7b4cc; }
  .compact-note { margin: 0; padding: 0 12px 10px; color: #a8b6cc; font-size: 10px; }
  .settings {
    padding: 13px 14px 14px;
    border-top: 1px solid #3b4960;
    background: #182130;
  }
  .settings-title { margin: 0 0 5px; font-size: 13px; font-weight: 700; }
  .settings-help { margin: 0 0 12px; color: #c7d1e3; font-size: 11px; }
  label { display: block; margin-bottom: 5px; color: #d9e3f4; font-size: 12px; }
  input {
    width: 100%;
    min-width: 0;
    height: 36px;
    padding: 7px 10px;
    border: 1px solid #53617a;
    border-radius: 8px;
    background: #101722;
    color: #f3f6fc;
    font-size: 14px;
    font-variant-numeric: tabular-nums;
  }
  input[aria-invalid="true"] { border-color: #fb7884; }
  .input-help { margin: 5px 0 11px; color: #a8b6cc; font-size: 10px; }
  .actions { display: flex; gap: 8px; }
  .save, .clear { min-height: 33px; padding: 6px 12px; font-size: 12px; font-weight: 650; }
  .save { flex: 1; background: #75e0c1; color: #102b26; }
  .save:hover { background: #93efd5; }
  .clear { border: 1px solid #4c5a72; background: transparent; color: #d9e3f4; }
  .clear:hover { background: #ffffff0a; }
  button:disabled { cursor: wait; opacity: .6; }
  .feedback { margin: 9px 0 0; color: #ffadb6; font-size: 11px; overflow-wrap: anywhere; }
  .feedback[data-kind="success"] { color: #9ce7ce; }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { transition: none !important; }
  }
  @media (max-width: 400px) {
    :host { top: 10px; right: 10px; }
    .card { width: min(276px, calc(100vw - 20px)); }
  }
`;

function element(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(options)) {
    if (key === 'text') node.textContent = value;
    else if (key === 'className') node.className = value;
    else node.setAttribute(key, String(value));
  }
  node.append(...children);
  return node;
}

function isCount(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function isBudget(value) {
  return isCount(value) && value > 0 && value <= MAX_BUDGET;
}

/** Mount an isolated, approximate visible-text token budget HUD. */
export function mountHud({ onBudgetChange } = {}) {
  const prefix = `astra-token-hud-${++mountCount}`;
  const host = element('div', { 'data-astra-token-hud': '' });
  const root = host.attachShadow({ mode: 'open' });
  const sheet = element('style', { text: styles });
  const title = element('p', { className: 'title', text: 'ASTRA · TOKENS' });
  const subtitle = element('p', { className: 'subtitle', text: 'งบข้อความโดยประมาณ' });
  const settingsButton = element('button', {
    type: 'button', className: 'icon-button', text: '⚙',
    title: 'ตั้งงบโทเคน', 'aria-label': 'ตั้งงบโทเคน',
    'aria-expanded': 'false', 'aria-controls': `${prefix}-settings`,
  });
  const collapseButton = element('button', {
    type: 'button', className: 'icon-button', text: '−',
    title: 'ย่อแถบโทเคน', 'aria-label': 'ย่อแถบโทเคน',
    'aria-expanded': 'true', 'aria-controls': `${prefix}-body`,
  });
  const header = element('div', { className: 'header' }, [
    element('span', { className: 'mark', text: '✦', 'aria-hidden': 'true' }),
    element('div', { className: 'heading' }, [title, subtitle]),
    settingsButton, collapseButton,
  ]);
  const balanceLabel = element('p', { className: 'balance-label', text: 'งบเหลือประมาณ' });
  const balance = element('p', { className: 'balance unknown', text: 'ยังไม่ทราบ' });
  const capacity = element('p', { className: 'capacity', text: 'ตั้งงบส่วนตัวเพื่อแสดงหลอดพลัง' });
  const fill = element('div', { className: 'fill' });
  const meter = element('div', {
    className: 'meter', role: 'progressbar', 'aria-label': 'งบโทเคนยังไม่ทราบ',
    'aria-valuemin': '0', 'aria-valuemax': '100', 'data-tone': 'unknown',
  }, [fill]);
  const usage = element('p', { className: 'usage', text: 'ใช้ไปประมาณ: ยังไม่ทราบ' });
  const note = element('p', { className: 'note' });
  note.hidden = true;
  const time = element('p', { className: 'time' });
  time.hidden = true;
  const body = element('div', { className: 'body', id: `${prefix}-body` }, [
    balanceLabel, balance, capacity, meter, usage, note,
    element('p', {
      className: 'footnote',
      text: 'ประมาณจากข้อความที่เห็น · ไม่ใช่โควตาบัญชี GPT',
    }), time,
  ]);
  const compactDot = element('span', { className: 'compact-dot', 'aria-hidden': 'true' });
  const compactText = element('span', { text: 'งบเหลือประมาณ: ยังไม่ทราบ' });
  const compact = element('div', { className: 'compact' }, [compactDot, compactText]);
  compact.hidden = true;
  const compactNote = element('p', {
    className: 'compact-note', text: 'ประมาณข้อความที่เห็น · ไม่ใช่โควตาบัญชี GPT',
  });
  compactNote.hidden = true;

  const budgetInput = element('input', {
    id: `${prefix}-budget`, type: 'number', inputmode: 'numeric',
    min: '1', max: String(MAX_BUDGET), step: '1', placeholder: 'เช่น 10000',
    autocomplete: 'off', 'aria-describedby': `${prefix}-help ${prefix}-feedback`,
  });
  const saveButton = element('button', { type: 'submit', className: 'save', text: 'บันทึกงบ' });
  const clearButton = element('button', { type: 'button', className: 'clear', text: 'ล้างงบ' });
  const feedback = element('p', {
    className: 'feedback', id: `${prefix}-feedback`, role: 'status', 'aria-live': 'polite',
  });
  feedback.hidden = true;
  const settings = element('form', {
    className: 'settings', id: `${prefix}-settings`, 'aria-label': 'ตั้งงบโทเคนส่วนตัว',
    novalidate: '',
  }, [
    element('p', { className: 'settings-title', text: 'ตั้งงบโทเคนส่วนตัว' }),
    element('p', {
      className: 'settings-help',
      text: 'หลอดนี้เทียบข้อความที่มองเห็นกับงบที่คุณตั้งเอง อ่านยอดคงเหลือหรือโควตาจริงของบัญชี GPT ไม่ได้',
    }),
    element('label', { for: `${prefix}-budget`, text: 'งบทั้งหมด (โทเคน)' }),
    budgetInput,
    element('p', {
      className: 'input-help', id: `${prefix}-help`,
      text: 'จำนวนเต็ม 1–10,000,000 · ใช้เป็นงบของบทสนทนานี้',
    }),
    element('div', { className: 'actions' }, [saveButton, clearButton]), feedback,
  ]);
  settings.hidden = true;
  const card = element('section', { className: 'card', 'aria-label': 'GPT Astra งบโทเคนโดยประมาณ' }, [
    header, body, compact, compactNote, settings,
  ]);
  root.append(sheet, card);
  document.documentElement.append(host);

  let destroyed = false;
  let busy = false;
  let collapsed = false;
  let lastBudget = null;
  let editDirty = false;

  function setFeedback(message, kind = 'error') {
    feedback.textContent = message;
    feedback.dataset.kind = kind;
    feedback.hidden = !message;
  }

  function toggleSettings(open) {
    settings.hidden = !open;
    settingsButton.setAttribute('aria-expanded', String(open));
    if (open) {
      if (!editDirty) budgetInput.value = lastBudget === null ? '' : String(lastBudget);
      budgetInput.focus();
    }
  }

  async function saveBudget(value) {
    if (busy || destroyed) return;
    if (typeof onBudgetChange !== 'function') {
      setFeedback('ยังบันทึกงบไม่ได้ กรุณาโหลดหน้าใหม่');
      return;
    }
    busy = true;
    budgetInput.disabled = true;
    saveButton.disabled = true;
    clearButton.disabled = true;
    setFeedback('');
    budgetInput.removeAttribute('aria-invalid');
    try {
      await onBudgetChange(value);
      if (destroyed) return;
      lastBudget = value;
      editDirty = false;
      budgetInput.value = value === null ? '' : String(value);
      setFeedback(value === null ? 'ล้างงบแล้ว' : 'บันทึกงบแล้ว', 'success');
    } catch (error) {
      if (destroyed) return;
      settings.hidden = false;
      settingsButton.setAttribute('aria-expanded', 'true');
      const detail = error instanceof Error && error.message ? `: ${error.message}` : '';
      setFeedback(`บันทึกงบไม่สำเร็จ${detail}`);
    } finally {
      if (!destroyed) {
        busy = false;
        budgetInput.disabled = false;
        saveButton.disabled = false;
        clearButton.disabled = false;
      }
    }
  }

  settingsButton.addEventListener('click', () => toggleSettings(settings.hidden));
  collapseButton.addEventListener('click', () => {
    collapsed = !collapsed;
    body.hidden = collapsed;
    compact.hidden = !collapsed;
    compactNote.hidden = !collapsed;
    collapseButton.textContent = collapsed ? '+' : '−';
    const label = collapsed ? 'ขยายแถบโทเคน' : 'ย่อแถบโทเคน';
    collapseButton.title = label;
    collapseButton.setAttribute('aria-label', label);
    collapseButton.setAttribute('aria-expanded', String(!collapsed));
    if (collapsed) toggleSettings(false);
  });
  budgetInput.addEventListener('input', () => {
    editDirty = true;
    budgetInput.removeAttribute('aria-invalid');
    setFeedback('');
  });
  settings.addEventListener('submit', (event) => {
    event.preventDefault();
    const raw = budgetInput.value.trim();
    const value = Number(raw);
    if (!/^\d+$/.test(raw) || !isBudget(value)) {
      budgetInput.setAttribute('aria-invalid', 'true');
      setFeedback('กรอกจำนวนเต็มตั้งแต่ 1 ถึง 10,000,000');
      budgetInput.focus();
      return;
    }
    void saveBudget(value);
  });
  clearButton.addEventListener('click', () => { void saveBudget(null); });
  root.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !settings.hidden) {
      event.preventDefault();
      event.stopPropagation();
      toggleSettings(false);
      settingsButton.focus();
    }
  });

  function update(snapshot = {}) {
    if (destroyed) return;
    const budget = isBudget(snapshot.budget) ? snapshot.budget : null;
    const used = isCount(snapshot.used) ? snapshot.used : null;
    const remaining = isCount(snapshot.remaining) && budget !== null && snapshot.remaining <= budget
      ? snapshot.remaining : null;
    const known = snapshot.status === 'ready' && budget !== null && used !== null && remaining !== null;
    const messages = isCount(snapshot.messages) ? snapshot.messages : 0;
    lastBudget = budget;
    if (!editDirty && !busy) budgetInput.value = budget === null ? '' : String(budget);

    balance.textContent = known ? numberFormat.format(remaining) : 'ยังไม่ทราบ';
    balance.classList.toggle('unknown', !known);
    balanceLabel.textContent = 'งบเหลือประมาณ';
    capacity.textContent = known
      ? `/ ${numberFormat.format(budget)} โทเคนที่ตั้งไว้`
      : budget === null ? 'ตั้งงบส่วนตัวเพื่อแสดงหลอดพลัง' : `งบที่ตั้งไว้ ${numberFormat.format(budget)} โทเคน`;
    usage.textContent = `${used === null ? 'ใช้ไปประมาณ: ยังไม่ทราบ' : `ใช้ไปประมาณ ${numberFormat.format(used)} โทเคน`} · ${numberFormat.format(messages)} ข้อความ`;
    compactText.textContent = known
      ? `งบเหลือประมาณ ${numberFormat.format(remaining)} / ${numberFormat.format(budget)}`
      : 'งบเหลือประมาณ: ยังไม่ทราบ';

    if (known) {
      const percent = Math.max(0, Math.min(100,
        typeof snapshot.percent === 'number' && Number.isFinite(snapshot.percent)
          ? snapshot.percent : remaining / budget * 100,
      ));
      const tone = percent <= 20 ? 'danger' : percent <= 50 ? 'warning' : 'healthy';
      const color = tone === 'danger' ? '#fb7884' : tone === 'warning' ? '#f4c55a' : '#6ee7b7';
      meter.dataset.tone = tone;
      meter.setAttribute('aria-valuenow', String(Math.round(percent)));
      meter.setAttribute('aria-valuetext', `งบเหลือประมาณ ${numberFormat.format(remaining)} จาก ${numberFormat.format(budget)} โทเคน`);
      meter.setAttribute('aria-label', 'งบโทเคนส่วนตัวที่เหลือโดยประมาณ');
      fill.style.width = `${percent}%`;
      compactDot.style.background = color;
    } else {
      meter.dataset.tone = 'unknown';
      meter.removeAttribute('aria-valuenow');
      meter.removeAttribute('aria-valuetext');
      meter.setAttribute('aria-label', 'งบโทเคนยังไม่ทราบ');
      fill.style.width = '0%';
      compactDot.style.background = '#a7b4cc';
    }

    const defaultNote = snapshot.status === 'error'
      ? 'อ่านข้อความไม่สำเร็จ กรุณาลองโหลดหน้าใหม่'
      : snapshot.status === 'unsupported'
        ? 'หน้านี้ยังไม่รองรับการอ่านบทสนทนา'
        : snapshot.status === 'waiting' ? 'รอข้อความในบทสนทนา…' : '';
    note.textContent = typeof snapshot.note === 'string' && snapshot.note.trim()
      ? snapshot.note : defaultNote;
    note.hidden = !note.textContent;
    const updatedAt = typeof snapshot.updatedAt === 'number' && Number.isFinite(snapshot.updatedAt)
      ? new Date(snapshot.updatedAt) : null;
    if (updatedAt && !Number.isNaN(updatedAt.getTime())) {
      time.textContent = `อัปเดต ${updatedAt.toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' })}`;
      time.hidden = false;
    } else {
      time.textContent = '';
      time.hidden = true;
    }
  }

  return {
    host,
    update,
    destroy() {
      if (destroyed) return;
      destroyed = true;
      host.remove();
    },
  };
}
