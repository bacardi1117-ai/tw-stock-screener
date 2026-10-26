export const DEFAULTS = Object.freeze({
  epsEnabled: true,
  positiveRequired: true,
  growthEnabled: true,
  minGrowth: 10,
  perEnabled: true,
  perMin: 0,
  perMax: 15,
  maDays: 20,
  deviationEnabled: true,
  deviationMin: -3,
  deviationMax: 3,
  pullbackEnabled: true,
  pullbackDays: 5,
  pullbackPct: 3,
  uptrendEnabled: false,
  uptrendDays: 5,
  sortField: 'deviation',
  sortDirection: 'asc',
});

export const STORAGE_KEY = 'tw-stock-eps-value-monthly-v1';
export function number(value) {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function annualPair(records = []) {
  const byYear = new Map(records
    .filter(item => Number.isInteger(Number(item.year)) && number(item.eps) !== null && item.basis === 'basic')
    .map(item => [Number(item.year), item]));
  const latestYear = Math.max(-Infinity, ...byYear.keys());
  const current = byYear.get(latestYear), previous = byYear.get(latestYear - 1);
  if (!current || !previous) return {current: null, previous: null, growth: null, scopeLabel: null,
    reason: '缺少最新連續兩個完整年度基本 EPS'};
  let scopeLabel;
  if (!current.verified_official || !previous.verified_official) {
    return {current, previous, growth: null, scopeLabel: null, reason: '缺少官方已驗證的完整年度基本 EPS（季度加總不替代年度值）'};
  }
  if (current.scope && previous.scope && current.scope === previous.scope) {
    scopeLabel = current.scope === 'consolidated' ? '合併' : '個體';
  } else {
    return {current, previous, growth: null, scopeLabel: null, reason: '兩年度 EPS 口徑無法確認一致'};
  }
  const oldEps = number(previous.eps), newEps = number(current.eps);
  const growth = oldEps > 0 && newEps > 0 ? Math.round((newEps / oldEps - 1) * 1e12) / 1e10 : null;
  return {current, previous, growth, scopeLabel,
    reason: growth === null ? 'EPS 資料存在，但兩年均須為正值才計算成長率' : null};
}

function buildMovingAverages(prices, period) {
  const ordered = [...prices].sort((a, b) => String(a[0]).localeCompare(String(b[0])));
  const close = ordered.map(item => number(item[1]));
  const averages = close.map((_, index) => index + 1 < period || close.slice(index - period + 1, index + 1).includes(null) ? null :
    close.slice(index - period + 1, index + 1).reduce((sum, value) => sum + value, 0) / period);
  return {ordered, close, averages};
}

export function evaluateRow(row, auxiliary, settings) {
  const reasons = [];
  const pair = annualPair(auxiliary?.annual_eps);
  const prices = (auxiliary?.prices ?? []).filter(item => !row.latest_date || String(item[0]) <= String(row.latest_date));
  const {ordered, close, averages} = buildMovingAverages(prices, settings.maDays);
  const index = ordered.length - 1;
  const currentClose = number(row.close) ?? close[index] ?? null;
  const ma = index >= 0 && (!row.latest_date || ordered[index][0] === row.latest_date) ? averages[index] : null;
  const deviation = currentClose !== null && ma > 0 ? (currentClose / ma - 1) * 100 : null;
  const checkResults = [];
  const addCheck = (enabled, value, missingReason, failureReason) => {
    if (!enabled) return;
    if (value === null) { checkResults.push('missing'); if (missingReason) reasons.push(missingReason); }
    else if (!value) { checkResults.push('fail'); if (failureReason) reasons.push(failureReason); }
    else checkResults.push('pass');
  };

  const epsNeeded = settings.epsEnabled && (settings.positiveRequired || settings.growthEnabled);
  if (epsNeeded && (!pair.current || !pair.previous)) reasons.push(pair.reason);
  if (settings.epsEnabled && settings.positiveRequired) {
    addCheck(true, pair.current && pair.previous && pair.scopeLabel
      ? number(pair.current.eps) > 0 && number(pair.previous.eps) > 0 : null,
    pair.reason, '兩年 EPS 須皆大於 0');
  }
  if (settings.epsEnabled && settings.growthEnabled) {
    const knownNonPositive = pair.scopeLabel && (number(pair.current.eps) <= 0 || number(pair.previous.eps) <= 0);
    addCheck(true, knownNonPositive ? false : pair.growth === null ? null : pair.growth >= settings.minGrowth,
      pair.reason || 'EPS 成長率無法計算', knownNonPositive ? '兩年 EPS 須皆大於 0 才能比較成長率' : `EPS 成長率低於 ${settings.minGrowth}%`);
  }

  const validValuations = [...(auxiliary?.valuations ?? []), {date: row.valuation_date, per: row.per}]
    .filter(item => item.date && number(item.per) > 0 && (!row.latest_date || item.date <= row.latest_date))
    .sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const valuation = validValuations.at(-1);
  const per = number(valuation?.per);
  const valuationDate = valuation?.date || null;
  addCheck(settings.perEnabled, per === null ? null : per > settings.perMin && per <= settings.perMax,
    '缺少附日期的有效本益比', `本益比不在 (${settings.perMin}, ${settings.perMax}] 範圍`);

  addCheck(settings.deviationEnabled, deviation === null ? null :
    deviation >= settings.deviationMin && deviation <= settings.deviationMax,
  `月線資料不足（需要 ${settings.maDays} 個交易日）`, `乖離率不在 ${settings.deviationMin}%～${settings.deviationMax}% 範圍`);

  if (settings.pullbackEnabled) {
    let seen = 0, hit = false;
    for (let i = index - 1; i >= Math.max(0, index - settings.pullbackDays); i -= 1) {
      if (averages[i] === null) continue;
      seen += 1;
      if (close[i] >= averages[i] * (1 + settings.pullbackPct / 100)) hit = true;
    }
    addCheck(true, seen < settings.pullbackDays ? null : hit,
      `回落檢查資料不足（需 ${settings.maDays + settings.pullbackDays} 個以上交易日）`,
      `前 ${settings.pullbackDays} 個交易日沒有收盤高於月線 ${settings.pullbackPct}%`);
  }

  if (settings.uptrendEnabled) {
    const earlierIndex = index - settings.uptrendDays;
    const earlierMa = earlierIndex >= 0 ? averages[earlierIndex] : null;
    addCheck(true, ma === null || earlierMa === null ? null : ma > earlierMa,
      `月線上揚資料不足（需 ${settings.maDays + settings.uptrendDays} 個以上交易日）`,
      `當日月線未高於 ${settings.uptrendDays} 個交易日前`);
  }

  const status = checkResults.includes('missing') ? 'missing_data' : checkResults.includes('fail') ? 'fail' : 'pass';
  const informationReasons = [...reasons];
  if (!pair.current || !pair.previous || !pair.scopeLabel) informationReasons.push(pair.reason);
  if (per === null || per <= 0) informationReasons.push('缺少有效本益比');
  if (ma === null) informationReasons.push(`月線資料不足（需要 ${settings.maDays} 個交易日）`);
  return {
    ...row,
    currentEps: pair.current,
    previousEps: pair.previous,
    epsGrowth: pair.growth,
    epsScopeLabel: pair.scopeLabel,
    epsReason: epsNeeded ? pair.reason : (pair.reason && (!pair.current || !pair.previous) ? pair.reason : null),
    per,
    valuationDate,
    closeDate: row.latest_date || (ordered[index]?.[0] ?? null),
    ma,
    deviation,
    status,
    reason: [...new Set(informationReasons.filter(Boolean))].join('；'),
    reasons: [...new Set(informationReasons.filter(Boolean))],
  };
}

export function evaluateRows(rows, auxiliaryByStock, settings) {
  return rows.map(row => evaluateRow(row, auxiliaryByStock?.[String(row.stock_id)], settings));
}

export function sortRows(rows, field, direction = 'asc') {
  const sign = direction === 'desc' ? -1 : 1;
  return [...rows].sort((a, b) => {
    const left = number(a[field]), right = number(b[field]);
    if (left === null && right === null) return String(a.stock_id).localeCompare(String(b.stock_id));
    if (left === null) return 1;
    if (right === null) return -1;
    return sign * (left - right) || String(a.stock_id).localeCompare(String(b.stock_id));
  });
}
