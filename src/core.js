export const MAX_BUDGET = 10_000_000;

export function parseBudget(value) {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value !== 'number' && typeof value !== 'string') {
    throw new Error('กรอกงบเป็นจำนวนเต็มบวก');
  }
  if (typeof value === 'string' && !/^\d+$/.test(value)) {
    throw new Error('กรอกงบเป็นจำนวนเต็มบวก');
  }
  const budget = Number(value);
  if (!Number.isSafeInteger(budget) || budget < 1 || budget > MAX_BUDGET) {
    throw new Error('งบต้องอยู่ระหว่าง 1 ถึง 10,000,000 โทเคน');
  }
  return budget;
}

export function makeSnapshot({ used = null, messages = 0, budget = null, status, note = '' }) {
  budget = parseBudget(budget);
  if (used !== null && (!Number.isSafeInteger(used) || used < 0)) {
    throw new Error('Invalid token count');
  }
  const remaining = used === null || budget === null ? null : Math.max(0, budget - used);
  return {
    status: status ?? (used === null ? 'waiting' : 'ready'),
    used,
    messages,
    budget,
    remaining,
    percent: remaining === null ? null : (remaining / budget) * 100,
    updatedAt: used === null ? null : Date.now(),
    note,
  };
}
