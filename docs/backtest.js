import {DEFAULT_BACKTEST, MISSING_DATA_REASONS, skippedDetailsToCsv, tradesToCsv} from './backtest_engine.mjs';

const $ = id => document.getElementById(id);
const form = $('backtestForm');
const storageKey = 'choose-stock-backtest-v1';
const numeric = new Set(Object.keys(DEFAULT_BACKTEST).filter(key =>
  !['startDate','endDate','rankBy','useCloseAboveShort','useShortAboveLong'].includes(key)));
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const money = value => Number.isFinite(value) ?
  Number(value).toLocaleString('zh-TW',{maximumFractionDigits:2}) : '—';
const percent = value => Number.isFinite(value) ? `${value.toFixed(2)}%` : '—';
let worker = null, result = null, manifest = null, busy = false;
let dateDefaults = {...DEFAULT_BACKTEST};

function fill(values) {
  for (const [key,value] of Object.entries(values)) {
    const element = form.elements.namedItem(key);
    if (!element) continue;
    if (element.type === 'checkbox') element.checked = Boolean(value);
    else element.value = value;
  }
}
function readConfig() {
  const config = {};
  for (const key of Object.keys(DEFAULT_BACKTEST)) {
    const element = form.elements.namedItem(key);
    config[key] = element.type === 'checkbox' ? element.checked :
      numeric.has(key) ? Number(element.value) : element.value;
  }
  return config;
}
function status(message, error = false) {
  $('runStatus').textContent = message;
  $('runStatus').classList.toggle('error-text', error);
}
function setBusy(value) {
  busy = value;
  $('runButton').disabled = value;
  $('cancelButton').hidden = !value;
}
function stopWorker() {
  worker?.terminate();
  worker = null;
  setBusy(false);
}
function chart(points, initialCapital) {
  if (!points.length) return null;
  const width = 900, height = 310, left = 75, right = 24, top = 38, bottom = 51;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const values = points.map(point => point.equity / 10000);
  const minimum = Math.min(...values, initialCapital / 10000);
  const maximum = Math.max(...values, initialCapital / 10000);
  const roughStep = Math.max((maximum - minimum) / 4, 1);
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const step = [1, 2, 5, 10].map(n => n * magnitude).find(n => n >= roughStep);
  let floor = Math.floor(minimum / step) * step;
  let ceiling = Math.ceil(maximum / step) * step;
  if (floor === ceiling) { floor -= step; ceiling += step; }
  const x = index => left + plotWidth * index / Math.max(points.length - 1, 1);
  const y = value => top + (ceiling - value / 10000) * plotHeight / (ceiling - floor);
  const path = points.map((point, index) =>
    `${index ? 'L' : 'M'}${x(index).toFixed(1)},${y(point.equity).toFixed(1)}`).join(' ');
  const yTicks = [];
  for (let value = floor; value <= ceiling + step / 1000; value += step) yTicks.push(value);
  const xTicks = [...new Set([0, 1, 2, 3, 4].map(n =>
    Math.round((points.length - 1) * n / 4)))];
  let peakIndex = 0, drawdownPeak = 0, drawdownLow = 0, largestDrawdown = 0;
  for (let i = 1; i < points.length; i++) {
    if (points[i].equity > points[peakIndex].equity) peakIndex = i;
    const drawdown = (points[peakIndex].equity - points[i].equity) / points[peakIndex].equity;
    if (drawdown > largestDrawdown) {
      largestDrawdown = drawdown;
      drawdownPeak = peakIndex;
      drawdownLow = i;
    }
  }
  const marker = (index, label, type) => {
    const cx = x(index), cy = y(points[index].equity);
    const textY = cy < top + 23 ? cy + 21 : cy - 10;
    const onRight = cx > width - 150;
    return `<circle cx="${cx}" cy="${cy}" r="5.5" class="chart-${type}"/>` +
      `<text x="${cx + (onRight ? -8 : 8)}" y="${textY}" text-anchor="${onRight ? 'end' : 'start'}" class="chart-marker-label chart-${type}-label">${label}</text>`;
  };
  const grid = yTicks.map(value => {
    const lineY = y(value * 10000);
    return `<line x1="${left}" y1="${lineY}" x2="${width - right}" y2="${lineY}" class="chart-grid"/>` +
      `<text x="${left - 10}" y="${lineY + 4}" text-anchor="end" class="chart-tick">${money(value)}</text>`;
  }).join('');
  const dates = xTicks.map(index => `<text x="${x(index)}" y="${height - 19}" text-anchor="${index === 0 ? 'start' : index === points.length - 1 ? 'end' : 'middle'}" class="chart-tick">${escapeHtml(points[index].date)}</text>`).join('');
  const baselineY = y(initialCapital);
  const baselineLabelY = baselineY < top + 18 ? baselineY + 16 : baselineY - 7;
  const svg = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" tabindex="0" aria-label="每日帳戶淨值圖；移動滑鼠或點選圖面查看各日數值，鍵盤可用左右方向鍵切換日期">
    ${grid}<line x1="${left}" y1="${top}" x2="${left}" y2="${height - bottom}" class="chart-axis"/>
    <line x1="${left}" y1="${height - bottom}" x2="${width - right}" y2="${height - bottom}" class="chart-axis"/>
    <text x="8" y="19" class="chart-axis-title">帳戶淨值（萬元）</text>
    <text x="${width - right}" y="${height - 4}" text-anchor="end" class="chart-axis-title">日期</text>
    ${dates}<line x1="${left}" y1="${baselineY}" x2="${width - right}" y2="${baselineY}" class="chart-baseline"/>
    <text x="${width - right - 5}" y="${baselineLabelY}" text-anchor="end" class="chart-baseline-label">初始資金 ${money(initialCapital / 10000)} 萬元</text>
    <path d="${path}" class="chart-line"/>
    ${largestDrawdown > 0 ? marker(drawdownPeak, '最大回撤高點', 'peak') + marker(drawdownLow, '最大回撤低點', 'trough') : ''}
    <line id="equityCursor" x1="${x(points.length - 1)}" y1="${top}" x2="${x(points.length - 1)}" y2="${height - bottom}" class="chart-cursor"/>
    <circle id="equitySelection" cx="${x(points.length - 1)}" cy="${y(points.at(-1).equity)}" r="5" class="chart-selection"/>
  </svg>`;
  return {svg, x, y, left, plotWidth, width};
}
function attachChartInteraction(points, initialCapital, model) {
  const svg = $('equityChart').querySelector('svg');
  const cursor = $('equityCursor'), selection = $('equitySelection');
  const inspector = $('equityInspector');
  let selected = points.length - 1;
  function show(index) {
    selected = Math.max(0, Math.min(points.length - 1, index));
    const point = points[selected];
    const posX = model.x(selected);
    cursor.setAttribute('x1', posX);
    cursor.setAttribute('x2', posX);
    selection.setAttribute('cx', posX);
    selection.setAttribute('cy', model.y(point.equity));
    const phase = point.phase === '期初' ? '（期初）' : '';
    inspector.textContent = `${point.date}${phase}　淨值 ${money(point.equity)} 元（${money(point.equity / 10000)} 萬元）　累積報酬率 ${percent((point.equity / initialCapital - 1) * 100)}`;
  }
  function nearest(event) {
    const box = svg.getBoundingClientRect();
    const localX = (event.clientX - box.left) * model.width / box.width;
    return Math.round((localX - model.left) / model.plotWidth * (points.length - 1));
  }
  svg.addEventListener('pointermove', event => {
    if (event.pointerType === 'mouse' || event.pointerType === 'pen') show(nearest(event));
  });
  svg.addEventListener('click', event => show(nearest(event)));
  svg.addEventListener('keydown', event => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    show(selected + (event.key === 'ArrowRight' ? 1 : -1));
  });
  show(selected);
}
function card(label, value, note = '') {
  return `<div class="card"><strong>${escapeHtml(label)}</strong><div class="count">${escapeHtml(value)}</div><small>${escapeHtml(note)}</small></div>`;
}
function render(data) {
  result = data;
  const s = data.summary;
  $('resultSection').hidden = false;
  $('resultLimits').textContent = `行情涵蓋 ${manifest.start} ～ ${manifest.end}，共 ${manifest.trading_dates.length} 個交易日。預留 120 個交易日暖機後可回測 ${manifest.backtest_start} ～ ${manifest.end}；個股仍可能因缺價或歷史不足而跳過。價格未經除權息調整，未含股利，並非完整含息總報酬；除權息跳價可能影響訊號與出場。目前股票清單缺少已下市股票，存在存活者偏誤。疑似漲跌停與盤中先後採保守估計。`;
  const p = data.performance;
  $('loadMetrics').textContent = p ? `本次行情傳輸檔案合計 ${(p.downloadBytes / 1048576).toFixed(2)} MiB（瀏覽器快取可減少實際傳輸）；保留 ${p.retainedRows.toLocaleString('zh-TW')} 筆日線。載入與解析 ${(p.loadMs / 1000).toFixed(2)} 秒，回測計算 ${(p.calculationMs / 1000).toFixed(2)} 秒。` : '';
  $('effectivePeriod').textContent = `${data.effectiveStart} ～ ${data.effectiveEnd}，${data.tradingDays} 個交易日`;
  $('summaryCards').innerHTML = [
    card('已平倉勝率', s.closedTrades ? percent(s.winRatePct) : '無已平倉交易', `${s.closedTrades} 筆已平倉`),
    card('帳戶累積報酬', percent(s.cumulativeReturnPct), `期末淨值 ${money(s.finalEquity)} 元`),
    card('年化報酬', percent(s.annualizedReturnPct), '依實際日曆期間年化；短期間波動大'),
    card('最大回撤', percent(s.maxDrawdownPct), '含初始資金'),
    card('平均獲利', s.closedTrades ? `${money(s.averageProfit)} 元` : '無已平倉交易', '僅獲利的已平倉交易'),
    card('平均虧損', s.closedTrades ? `${money(s.averageLoss)} 元` : '無已平倉交易', '僅虧損的已平倉交易'),
  ].join('');
  const chartModel = chart(data.equityCurve, data.config.initialCapital);
  $('equityChart').innerHTML = chartModel?.svg ?? '';
  if (chartModel) attachChartInteraction(data.equityCurve, data.config.initialCapital, chartModel);
  $('equityRange').textContent = `虛線為初始資金 ${money(data.config.initialCapital)} 元；期末 ${money(s.finalEquity)} 元。未平倉按最後可用價格估值。`;
  const skipLabels = {warmup_insufficient:'暖機不足',unable_to_fill:'無法成交／疑似鎖死',
    insufficient_cash:'資金不足取消',cash_reduced:'資金不足而縮減張數'};
  const otherSkips = Object.entries(skipLabels).map(([key,label]) =>
    `<div><strong>${escapeHtml(label)}</strong><span>${Number(data.skipped[key] ?? 0).toLocaleString('zh-TW')} 次</span></div>`);
  const missingCards = Object.entries(MISSING_DATA_REASONS).map(([key,label]) => {
    const stat = data.missingDiagnostics?.[key] ?? {events:0,stockCount:0};
    return `<div><strong>${escapeHtml(label)}</strong><span>${Number(stat.events).toLocaleString('zh-TW')} 次<br>${Number(stat.stockCount).toLocaleString('zh-TW')} 支股票</span></div>`;
  });
  $('skipStats').innerHTML = [...missingCards, ...otherSkips].join('');
  $('openRows').innerHTML = data.openPositions.length ? data.openPositions.map(p => `<tr>
    <td>${escapeHtml(p.stock_id)} ${escapeHtml(p.stock_name)}</td><td>${escapeHtml(p.entry_date)}</td>
    <td>${money(p.shares)}</td><td>${money(p.entry_price)}</td><td>${money(p.last_price)}${p.stale ? '（過期）' : ''}</td>
    <td>${escapeHtml(p.last_price_date)}</td><td>${escapeHtml(p.exit_intent ?? '—')}</td></tr>`).join('') :
    '<tr><td colspan="7">期末沒有未平倉部位</td></tr>';
  $('tradeRows').innerHTML = data.trades.length ? data.trades.map(t => `<tr>
    <td>${escapeHtml(t.stock_id)} ${escapeHtml(t.stock_name)}</td>
    <td>${escapeHtml(t.entry_date)}<br>${escapeHtml(t.exit_date)}</td>
    <td>${money(t.entry_price)}<br>${money(t.exit_price)}</td><td>${money(t.shares)}</td>
    <td>${money(t.entry_gross + t.entry_fee)}</td>
    <td>${money(t.exit_gross - t.exit_fee - t.sell_tax)}</td>
    <td class="${t.net_pnl >= 0 ? 'profit' : 'loss'}">${money(t.net_pnl)}</td>
    <td>${percent(t.return_pct)}</td><td>${escapeHtml(t.exit_reason)}</td></tr>`).join('') :
    '<tr><td colspan="9">無已平倉交易</td></tr>';
}
async function loadManifest() {
  const response = await fetch('./data/backtest/manifest.json');
  if (!response.ok) throw new Error('無法載入回測資料清單');
  manifest = await response.json();
  if (manifest.schema_version !== 1 || manifest.volume_unit !== 'shares' || !manifest.trading_dates?.length) {
    throw new Error('回測資料清單格式不正確');
  }
  for (const key of ['startDate','endDate']) {
    form.elements.namedItem(key).min = manifest.backtest_start ?? manifest.start;
    form.elements.namedItem(key).max = manifest.end;
  }
  dateDefaults = {...DEFAULT_BACKTEST,
    startDate:manifest.recent_year_start > manifest.backtest_start ? manifest.recent_year_start : manifest.backtest_start,
    endDate:manifest.end};
  const current = readConfig();
  if (!current.startDate || !current.endDate) fill({...current,...{startDate:dateDefaults.startDate,endDate:dateDefaults.endDate}});
  const totalBytes = manifest.years.reduce((sum,y) => sum + (y.compressed_bytes ?? y.bytes ?? 0), 0);
  const yearCoverage = manifest.recent_year_complete ? `最近完整一年：${manifest.recent_year_start} ～ ${manifest.end}；起日前已有 ${manifest.recent_year_warmup_sessions} 個交易日。` : '一年回測所需的歷史或暖機資料尚未齊備。';
  $('coverageNotice').textContent = `行情涵蓋 ${manifest.start} ～ ${manifest.end}，${manifest.trading_dates.length} 個交易日、${manifest.stock_count.toLocaleString('zh-TW')} 支目前清單中的普通股。預留 120 個交易日暖機後可回測 ${manifest.backtest_start ?? '尚不足 120 日'} ～ ${manifest.end}。${yearCoverage}成交量單位：股。`;
  $('downloadNotice').textContent = `全年度壓縮行情約 ${(totalBytes/1048576).toFixed(2)} MiB。背景程式依期間載入年度檔，只保留所需日期；手機首次載入可能較慢，請保持頁面開啟。個股缺漏不補價，未確認上市日期的歷史不足不標為新上市。`;
}
function start() {
  if (busy) return;
  const config = readConfig();
  if (!form.reportValidity()) return;
  if (config.startDate > config.endDate) {status('開始日期不得晚於結束日期', true);return;}
  if (config.maShort >= config.maLong) {status('短均線必須短於長均線', true);return;}
  try {localStorage.setItem(storageKey, JSON.stringify(config));} catch { /* Private browsing can disable storage. */ }
  $('resultSection').hidden = true;
  status('準備行情…');
  setBusy(true);
  try { worker ??= new Worker(new URL('./backtest_worker.mjs', import.meta.url), {type:'module'}); }
  catch { status('無法啟動背景回測，請確認瀏覽器支援 Web Worker',true);setBusy(false);return; }
  worker.onmessage = event => {
    const message = event.data;
    if (message?.type === 'progress') status(message.message);
    else if (message?.type === 'result') {render(message.result);status('回測完成');setBusy(false);}
    else if (message?.type === 'error') {status(message.message || '回測失敗',true);setBusy(false);}
  };
  worker.onerror = () => {status('背景回測執行失敗，請重試',true);stopWorker();};
  worker.onmessageerror = () => {status('背景回測回傳資料失敗，請重試',true);stopWorker();};
  try { worker.postMessage({type:'run',config}); }
  catch { status('無法送出回測參數，請重試',true);stopWorker(); }
}

form.addEventListener('submit', event => {event.preventDefault();start();});
$('cancelButton').addEventListener('click',()=>{stopWorker();status('已取消本次回測');});
$('resetButton').addEventListener('click',()=>{fill(dateDefaults);status('已恢復首組數值參數，期間設為最近完整一年');});
$('downloadCsv').addEventListener('click',()=>{
  if (!result) return;
  const blob = new Blob([tradesToCsv(result.trades)], {type:'text/csv;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `backtest-trades-${result.effectiveStart}-${result.effectiveEnd}.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url),1000);
});
$('downloadSkipCsv').addEventListener('click',()=>{
  if (!result) return;
  const blob = new Blob([skippedDetailsToCsv(result.skipDetails ?? [])], {type:'text/csv;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `backtest-skipped-${result.effectiveStart}-${result.effectiveEnd}.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url),1000);
});
try {
  const saved = JSON.parse(localStorage.getItem(storageKey));
  fill(saved && typeof saved === 'object' ? {...DEFAULT_BACKTEST,...saved} : DEFAULT_BACKTEST);
} catch {fill(DEFAULT_BACKTEST);}
loadManifest().catch(error=>{
  $('coverageNotice').textContent = error.message;
  $('coverageNotice').classList.add('error');
  $('runButton').disabled = true;
});
