import {parsePricesCsv, runBacktest} from './backtest_engine.mjs';

let manifest = null;
const yearlyRows = new Map();

async function getManifest() {
  if (manifest) return manifest;
  const response = await fetch(new URL('./data/backtest/manifest.json', import.meta.url));
  if (!response.ok) throw new Error(`無法載入回測資料清單（HTTP ${response.status}）`);
  const found = await response.json();
  if (found.schema_version !== 1 || found.volume_unit !== 'shares' ||
      found.lot_size_shares !== 1000 || !Array.isArray(found.trading_dates) ||
      !Array.isArray(found.years)) throw new Error('回測資料清單格式不正確');
  manifest = found;
  return manifest;
}

self.onmessage = async event => {
  if (event.data?.type !== 'run') return;
  try {
    const config = event.data.config;
    const data = await getManifest();
    const dates = data.trading_dates;
    const first = dates.findIndex(day => day >= config.startDate);
    const warmup = Math.max(config.maLong, config.maShort, config.returnDays + 1,
                            config.volumeDays) + 1;
    const earliest = dates[Math.max(0, first - warmup)] ?? dates[0];
    const years = data.years.filter(item => item.end >= earliest && item.start <= config.endDate);
    if (!years.length) throw new Error('選定期間沒有行情檔');
    for (const item of years) {
      if (yearlyRows.has(item.year)) continue;
      self.postMessage({type: 'progress', message: `載入 ${item.year} 年行情…`});
      const response = await fetch(new URL(`./data/backtest/${item.file}`, import.meta.url));
      if (!response.ok) throw new Error(`無法載入 ${item.year} 年行情（HTTP ${response.status}）`);
      const parsed = parsePricesCsv(await response.text());
      if (parsed.length !== item.rows) throw new Error(`${item.year} 年行情筆數不符`);
      yearlyRows.set(item.year, parsed);
    }
    const rows = years.flatMap(item => yearlyRows.get(item.year));
    self.postMessage({type: 'progress', message: `計算 ${rows.length.toLocaleString()} 筆日線…`});
    const result = runBacktest(rows, config, data.stocks);
    self.postMessage({type: 'result', result});
  } catch (error) {
    const message = error instanceof TypeError && /fetch/i.test(error.message) ?
      '行情檔載入失敗，請檢查連線後重試' :
      error instanceof Error ? error.message : '回測失敗';
    self.postMessage({type: 'error', message});
  }
};
