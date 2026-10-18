// Pure daily-bar simulator. No API, current factor, or strategy snapshot is read here.
export const LOT_SIZE = 1000;
export const DEFAULT_BACKTEST = Object.freeze({
  startDate: '2026-07-15', endDate: '2026-10-14', initialCapital: 5000000,
  maxPositions: 5, maShort: 20, maLong: 60,
  useCloseAboveShort: true, useShortAboveLong: true,
  returnDays: 20, minReturnPct: 0, volumeDays: 20, minAvgVolumeShares: 100000,
  takeProfitPct: 15, stopLossPct: 8, maxHoldDays: 20,
  feeRatePct: 0.1425, feeMinimum: 20, sellTaxPct: 0.3, slippagePct: 0.1,
  rankBy: 'return_desc',
});

const round2 = n => Math.round((n + Number.EPSILON) * 100) / 100;
export const MISSING_DATA_REASONS = Object.freeze({
  current_quote_missing: '當日行情缺漏',
  lookback_gap: '指標回看區間缺漏',
  history_too_short: '歷史長度不足',
  outside_coverage: '超出資料涵蓋期間',
});
const validBar = bar => bar && ['open','high','low','close','volume'].every(k => Number.isFinite(bar[k])) &&
  bar.open > 0 && bar.high > 0 && bar.low > 0 && bar.close > 0 && bar.volume > 0;

export function parsePricesCsv(csv) {
  const lines = csv.replace(/^\uFEFF/, '').trim().split(/\r?\n/);
  const expected = 'date,stock_id,open,high,low,close,volume';
  if (lines.shift() !== expected) throw new Error('回測行情欄位不符');
  return lines.filter(Boolean).map((line, index) => {
    const fields = line.split(',');
    if (fields.length !== 7) throw new Error(`行情第 ${index + 2} 行格式不符`);
    const [date, stock_id, ...values] = fields;
    const [open, high, low, close, volume] = values.map(Number);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^\d{4}$/.test(stock_id) ||
        ![open, high, low, close, volume].every(Number.isFinite) ||
        [open, high, low, close].some(value => value <= 0) || volume < 0) {
      throw new Error(`行情第 ${index + 2} 行數值不正確`);
    }
    return {date, stock_id, open, high, low, close, volume};
  });
}

export function validateBacktestConfig(input, dates) {
  const c = {...input};
  if (!Array.isArray(dates) || !dates.length) throw new Error('沒有可用交易日');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(c.startDate) || !/^\d{4}-\d{2}-\d{2}$/.test(c.endDate) ||
      c.startDate > c.endDate || c.endDate < dates[0] || c.startDate > dates.at(-1)) {
    throw new Error('回測日期不在行情範圍內');
  }
  for (const field of ['initialCapital','minReturnPct','minAvgVolumeShares','takeProfitPct',
                       'stopLossPct','feeRatePct','feeMinimum','sellTaxPct','slippagePct']) {
    if (!Number.isFinite(c[field])) throw new Error(`${field} 必須是有效數值`);
  }
  for (const field of ['maxPositions','maShort','maLong','returnDays','volumeDays','maxHoldDays']) {
    if (!Number.isInteger(c[field]) || c[field] < 1 || c[field] > 120) {
      throw new Error(`${field} 必須是 1 至 120 的整數`);
    }
  }
  if (c.initialCapital <= 0 || c.maxPositions > 50 || c.maShort >= c.maLong ||
      c.minAvgVolumeShares < 0 || c.stopLossPct <= 0 || c.stopLossPct >= 100 ||
      c.takeProfitPct <= 0 || c.feeRatePct < 0 || c.feeRatePct > 10 ||
      c.feeMinimum < 0 || c.sellTaxPct < 0 || c.sellTaxPct > 10 ||
      c.slippagePct < 0 || c.slippagePct > 10 ||
      !['return_desc','volume_desc','stock_id'].includes(c.rankBy)) {
    throw new Error('回測參數超出允許範圍');
  }
  return c;
}

function fee(gross, config) {
  return round2(Math.max(gross * config.feeRatePct / 100, config.feeMinimum));
}
function purchaseCost(shares, rawPrice, config) {
  const price = rawPrice * (1 + config.slippagePct / 100);
  const gross = round2(shares * price);
  return {price, gross, fee: fee(gross, config), total: round2(gross + fee(gross, config))};
}
function affordableShares(budget, rawPrice, config, cap = Infinity) {
  if (!Number.isFinite(rawPrice) || rawPrice <= 0 || budget <= 0) return 0;
  let lots = Math.floor(Math.min(cap, budget / (rawPrice * (1 + config.slippagePct / 100))) / LOT_SIZE);
  while (lots > 0 && purchaseCost(lots * LOT_SIZE, rawPrice, config).total > budget + 1e-8) lots--;
  return lots * LOT_SIZE;
}

function limitLocked(bar, previous, direction) {
  if (!validBar(bar) || !previous || !Number.isFinite(previous.close) || previous.close <= 0) return false;
  const onePrice = Math.max(bar.open, bar.high, bar.low, bar.close) -
    Math.min(bar.open, bar.high, bar.low, bar.close) < 1e-7;
  const change = bar.open / previous.close - 1;
  return onePrice && (direction === 'up' ? change >= 0.095 : change <= -0.095);
}

export function runBacktest(rows, input, stockInfo = {}) {
  if (!Array.isArray(rows) || !rows.length) throw new Error('沒有行情資料');
  const dates = [...new Set(rows.map(row => row.date))].sort();
  const config = validateBacktestConfig(input, dates);
  const byDate = dates.map(() => new Map());
  const indexOfDate = new Map(dates.map((date, index) => [date, index]));
  for (const row of rows) {
    const bucket = byDate[indexOfDate.get(row.date)];
    if (bucket.has(row.stock_id)) throw new Error(`重複行情：${row.date} ${row.stock_id}`);
    bucket.set(row.stock_id, row);
  }
  const observedBounds = new Map();
  for (let i = 0; i < byDate.length; i++) {
    for (const id of byDate[i].keys()) {
      const bounds = observedBounds.get(id) ?? {first: i, last: i};
      bounds.last = i;
      observedBounds.set(id, bounds);
    }
  }
  const ids = Object.keys(stockInfo).length ? Object.keys(stockInfo).sort() :
    [...new Set(rows.map(row => row.stock_id))].sort();
  const startIndex = dates.findIndex(day => day >= config.startDate);
  let endIndex = dates.findLastIndex(day => day <= config.endDate);
  if (startIndex < 0 || endIndex < startIndex) throw new Error('回測期間沒有交易日');
  const effectiveStart = dates[startIndex], effectiveEnd = dates[endIndex];
  let cash = config.initialCapital, receivable = 0, pendingBuys = [];
  const positions = new Map(), trades = [];
  const skipped = {warmup_insufficient: 0, missing_data: 0, unable_to_fill: 0,
                   insufficient_cash: 0, cash_reduced: 0};
  const missingDiagnostics = Object.fromEntries(Object.keys(MISSING_DATA_REASONS).map(key =>
    [key, {events: 0, stockIds: new Set()}]));
  const skipDetails = [];
  function recordMissing(id, dayIndex, reason) {
    const diagnostic = missingDiagnostics[reason];
    if (!diagnostic) return;
    const stockId = String(id);
    diagnostic.events++;
    diagnostic.stockIds.add(stockId);
    skipDetails.push({date: dates[dayIndex], stock_id: stockId, reason});
  }
  function classifyMissing(id, dayIndex, kind) {
    const bounds = observedBounds.get(id);
    if (!bounds) return 'outside_coverage';
    if (kind === 'lookback' && dayIndex < bounds.first) return 'history_too_short';
    if (dayIndex < bounds.first || dayIndex > bounds.last) return 'outside_coverage';
    if (kind === 'current') return 'current_quote_missing';
    const bar = byDate[dayIndex].get(id);
    if (!bar || !validBar(bar)) {
      return 'lookback_gap';
    }
    return 'lookback_gap';
  }
  const equityCurve = [{date: effectiveStart, equity: config.initialCapital, phase: '期初'}];

  function windowFor(id, dayIndex, length) {
    if (dayIndex - length + 1 < 0) return {reason: 'warmup_insufficient'};
    const result = [];
    for (let i = dayIndex - length + 1; i <= dayIndex; i++) {
      const bar = byDate[i].get(id);
      if (!validBar(bar)) {
        recordMissing(id, i, classifyMissing(id, i, 'lookback'));
        return {reason: 'missing_data'};
      }
      result.push(bar);
    }
    return {bars: result};
  }
  function candidate(id, dayIndex) {
    if (!validBar(byDate[dayIndex].get(id))) {
      recordMissing(id, dayIndex, classifyMissing(id, dayIndex, 'current'));
      return {reason: 'missing_data'};
    }
    const lengths = [config.returnDays + 1, config.volumeDays];
    if (config.useCloseAboveShort || config.useShortAboveLong) lengths.push(config.maShort);
    if (config.useShortAboveLong) lengths.push(config.maLong);
    const lookback = windowFor(id, dayIndex, Math.max(...lengths));
    if (lookback.reason) return lookback;
    const bars = lookback.bars;
    const today = bars.at(-1);
    const avg = n => bars.slice(-n).reduce((sum, item) => sum + item.close, 0) / n;
    const avgVolume = bars.slice(-config.volumeDays).reduce((sum, item) => sum + item.volume, 0) / config.volumeDays;
    const returnPct = (today.close / bars.at(-config.returnDays - 1).close - 1) * 100;
    const matches = (!config.useCloseAboveShort || today.close > avg(config.maShort)) &&
      (!config.useShortAboveLong || avg(config.maShort) > avg(config.maLong)) &&
      returnPct >= config.minReturnPct && avgVolume >= config.minAvgVolumeShares;
    return {matches, close: today.close, returnPct, avgVolume};
  }
  function sortCandidates(a, b) {
    const difference = config.rankBy === 'return_desc' ? b.returnPct - a.returnPct :
      config.rankBy === 'volume_desc' ? b.avgVolume - a.avgVolume : 0;
    return difference || a.id.localeCompare(b.id);
  }
  function prepareBuys(dayIndex) {
    if (dayIndex < 0 || dayIndex >= endIndex) return [];
    const freeSlots = config.maxPositions - positions.size;
    if (freeSlots <= 0) return [];
    const candidates = [];
    for (const id of ids) {
      if (positions.has(id)) continue;
      const signal = candidate(id, dayIndex);
      if (signal.reason) skipped[signal.reason]++;
      else if (signal.matches) candidates.push({id, ...signal});
    }
    candidates.sort(sortCandidates);
    // Sale proceeds received today are available at tomorrow's opening, never today's.
    const allocation = (cash + receivable) / freeSlots;
    const planned = [];
    for (const item of candidates) {
      if (planned.length >= freeSlots) break;
      const shares = affordableShares(allocation, item.close, config);
      if (shares < LOT_SIZE) {
        skipped.insufficient_cash++;
        continue;
      }
      planned.push({id: item.id, plannedShares: shares});
    }
    return planned;
  }
  function executable(id, bar, dayIndex, side) {
    if (!bar) return 'missing_data';
    if (!validBar(bar)) return 'unable_to_fill';
    const previous = dayIndex > 0 ? byDate[dayIndex - 1].get(id) : null;
    if (limitLocked(bar, previous, side === 'buy' ? 'up' : 'down')) return 'unable_to_fill';
    return null;
  }
  function sell(position, rawPrice, date, reason) {
    const price = rawPrice * (1 - config.slippagePct / 100);
    const gross = round2(price * position.shares);
    const sellingFee = fee(gross, config);
    const tax = round2(gross * config.sellTaxPct / 100);
    const net = round2(gross - sellingFee - tax);
    receivable = round2(receivable + net);
    const pnl = round2(net - position.entryGross - position.entryFee);
    trades.push({stock_id: position.id, stock_name: stockInfo[position.id]?.name ?? '',
      entry_date: position.entryDate, exit_date: date, entry_price: position.entryPrice,
      exit_price: price, shares: position.shares, entry_gross: position.entryGross,
      entry_fee: position.entryFee, exit_gross: gross, exit_fee: sellingFee,
      sell_tax: tax, net_pnl: pnl,
      return_pct: (net / (position.entryGross + position.entryFee) - 1) * 100,
      exit_reason: reason});
    positions.delete(position.id);
  }
  function trigger(position, bar) {
    const stop = position.entryPrice * (1 - config.stopLossPct / 100);
    const take = position.entryPrice * (1 + config.takeProfitPct / 100);
    if (bar.open <= stop) return {reason: '停損', price: bar.open};
    if (bar.open >= take) return {reason: '停利', price: bar.open};
    if (bar.low <= stop) return {reason: '停損', price: stop};
    if (bar.high >= take) return {reason: '停利', price: take};
    return null;
  }

  if (startIndex > 0) pendingBuys = prepareBuys(startIndex - 1);
  for (let dayIndex = startIndex; dayIndex <= endIndex; dayIndex++) {
    const date = dates[dayIndex];
    cash = round2(cash + receivable);
    receivable = 0;
    const openingCash = cash;
    for (const position of [...positions.values()].sort((a,b) => a.id.localeCompare(b.id))) {
      const bar = byDate[dayIndex].get(position.id);
      if (position.exitIntent) {
        const failure = executable(position.id, bar, dayIndex, 'sell');
        if (failure) {
          skipped[failure]++;
          if (failure === 'missing_data') recordMissing(position.id, dayIndex,
            classifyMissing(position.id, dayIndex, 'current'));
        }
        else sell(position, bar.open, date, position.exitIntent);
      } else if (validBar(bar)) {
        const stop = position.entryPrice * (1 - config.stopLossPct / 100);
        const take = position.entryPrice * (1 + config.takeProfitPct / 100);
        const reason = bar.open <= stop ? '停損' : bar.open >= take ? '停利' : null;
        if (reason) {
          const failure = executable(position.id, bar, dayIndex, 'sell');
          if (failure) {position.exitIntent = reason; skipped[failure]++;}
          else sell(position, bar.open, date, reason);
        }
      }
    }
    // Opening sales become receivables; their proceeds cannot fund any of these buys.
    let remainingOpeningCash = openingCash;
    for (const order of pendingBuys) {
      if (positions.has(order.id) || positions.size >= config.maxPositions) continue;
      const bar = byDate[dayIndex].get(order.id);
      const failure = executable(order.id, bar, dayIndex, 'buy');
      if (failure) {skipped[failure]++; continue;}
      const shares = affordableShares(remainingOpeningCash, bar.open, config, order.plannedShares);
      if (shares < LOT_SIZE) {skipped.insufficient_cash++; continue;}
      if (shares < order.plannedShares) skipped.cash_reduced++;
      const cost = purchaseCost(shares, bar.open, config);
      remainingOpeningCash = round2(remainingOpeningCash - cost.total);
      cash = round2(cash - cost.total);
      positions.set(order.id, {id: order.id, shares, entryDate: date, entryIndex: dayIndex,
        entryPrice: cost.price, entryGross: cost.gross, entryFee: cost.fee,
        lastPrice: bar.close, lastPriceDate: date, exitIntent: null});
    }
    pendingBuys = [];
    for (const position of [...positions.values()].sort((a,b) => a.id.localeCompare(b.id))) {
      const bar = byDate[dayIndex].get(position.id);
      if (!validBar(bar)) {
        if (!position.exitIntent) {
          skipped.missing_data++;
          recordMissing(position.id, dayIndex, classifyMissing(position.id, dayIndex, 'current'));
        }
        continue;
      }
      position.lastPrice = bar.close;
      position.lastPriceDate = date;
      if (position.exitIntent) continue;
      const event = trigger(position, bar);
      if (event) {
        const failure = executable(position.id, bar, dayIndex, 'sell');
        if (failure) {position.exitIntent = event.reason; skipped[failure]++;}
        else {sell(position, event.price, date, event.reason); continue;}
      }
      if (!position.exitIntent && dayIndex - position.entryIndex + 1 >= config.maxHoldDays) {
        position.exitIntent = '到期';
      }
    }
    const holdings = [...positions.values()].reduce((sum, p) => sum + p.shares * p.lastPrice, 0);
    equityCurve.push({date, equity: round2(cash + receivable + holdings),
      cash, receivable, holdings: round2(holdings), phase: '收盤'});
    if (dayIndex < endIndex) pendingBuys = prepareBuys(dayIndex);
  }
  const finalEquity = equityCurve.at(-1).equity;
  const closed = trades.length, wins = trades.filter(t => t.net_pnl > 0);
  const profits = trades.filter(t => t.net_pnl > 0).map(t => t.net_pnl);
  const losses = trades.filter(t => t.net_pnl < 0).map(t => t.net_pnl);
  let peak = config.initialCapital, maxDrawdownPct = 0;
  for (const point of equityCurve) {
    peak = Math.max(peak, point.equity);
    maxDrawdownPct = Math.max(maxDrawdownPct, (peak - point.equity) / peak * 100);
  }
  const calendarDays = (Date.parse(effectiveEnd) - Date.parse(effectiveStart)) / 86400000;
  const annualizedReturnPct = calendarDays > 0 && finalEquity > 0 ?
    ((finalEquity / config.initialCapital) ** (365 / calendarDays) - 1) * 100 : null;
  return {config, effectiveStart, effectiveEnd, tradingDays: endIndex - startIndex + 1,
    summary: {closedTrades: closed, winRatePct: closed ? wins.length / closed * 100 : null,
      averageProfit: profits.length ? profits.reduce((a,b) => a+b, 0) / profits.length : null,
      averageLoss: losses.length ? losses.reduce((a,b) => a+b, 0) / losses.length : null,
      cumulativeReturnPct: (finalEquity / config.initialCapital - 1) * 100,
      annualizedReturnPct, maxDrawdownPct, finalEquity},
    equityCurve, trades, skipped,
    missingDiagnostics: Object.fromEntries(Object.entries(missingDiagnostics).map(([key, value]) =>
      [key, {events: value.events, stockCount: value.stockIds.size}])),
    skipDetails,
    openPositions: [...positions.values()].map(p => ({stock_id:p.id,
      stock_name:stockInfo[p.id]?.name ?? '', shares:p.shares, entry_date:p.entryDate,
      entry_price:p.entryPrice, last_price:p.lastPrice, last_price_date:p.lastPriceDate,
      market_value:round2(p.shares*p.lastPrice), stale:p.lastPriceDate !== effectiveEnd,
      exit_intent:p.exitIntent})),
    warnings: ['價格未經除權息調整，結果為未含息價格回測，價格跳動可能影響訊號與停損。',
      '目前只有 133 個交易日；以目前股票清單回推存在存活者偏誤。',
      '疑似漲跌停鎖死僅按日線推估；日內先後無法辨別時先算停損。'],
  };
}

export function tradesToCsv(trades) {
  const fields = ['stock_id','stock_name','entry_date','exit_date','entry_price','exit_price',
    'shares','entry_gross','entry_fee','exit_gross','exit_fee','sell_tax','net_pnl',
    'return_pct','exit_reason'];
  const safe = value => {
    let text = String(value ?? '');
    if (/^[=+\-@]/.test(text) && !/^-?\d+(\.\d+)?$/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"','""')}"`;
  };
  return '\uFEFF' + [fields.join(','), ...trades.map(trade => fields.map(key => safe(trade[key])).join(','))].join('\r\n') + '\r\n';
}

export function skippedDetailsToCsv(details) {
  const safe = value => `"${String(value ?? '').replaceAll('"', '""')}"`;
  const rows = [['date', 'stock_id', 'reason'], ...details.map(item => [
    item.date, item.stock_id, MISSING_DATA_REASONS[item.reason] ?? item.reason,
  ])];
  return '\uFEFF' + rows.map(row => row.map(safe).join(',')).join('\r\n') + '\r\n';
}
