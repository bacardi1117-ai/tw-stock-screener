import {evaluateRows, filterRows, sortRows, strategyKeys, number} from './engine.mjs';
import {loadSettings, saveSettings} from './settings_state.mjs';

const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const fmt = (value, digits=1) => number(value) === null ? '—' : Number(value).toLocaleString('zh-TW',{maximumFractionDigits:digits,minimumFractionDigits:0});
const labels = {pass:'符合',fail:'未符合',missing_data:'資料不足',unavailable:'尚不可用'};
let defaults, config, rawRows = [], evaluated = [];

function showNotice() {
  const messages = ['策略 C：估值資料待補（PBR 與完整年度紀錄）','策略 D：法人資料待補','策略 E：股利資料待補'];
  if (config.universe.min_price < config.universe.downloaded_min_price ||
      (!config.universe.exclude_financials && config.universe.downloaded_exclude_financials)) {
    messages.unshift('此設定超出目前已下載的基本面資料母體，需重新執行資料更新才能完整套用。');
  }
  $('dataNotice').textContent = messages.join('　｜　');
  $('dataNotice').hidden = false;
}
function renderCounts() {
  const base = evaluated.filter(row => number(row.close) !== null && number(row.close) >= config.universe.min_price &&
    (!config.universe.exclude_financials || row.is_financial !== true));
  $('universeCount').textContent = base.length.toLocaleString('zh-TW');
  $('strategyCounts').innerHTML = strategyKeys.map((key,index) => {
    const count = base.filter(row => row[key] === 'pass').length;
    const unavailable = base.every(row => row[key] === 'unavailable');
    return `<div class="card"><strong>策略 ${'ABCDE'[index]} · ${escapeHtml(config[key].label)}</strong><div class="count">${count}</div><small>${unavailable ? config[key].unavailable_message ?? '資料尚不可用' : '支符合目前條件'}</small></div>`;
  }).join('');
}
function render() {
  showNotice();
  renderCounts();
  const selected = [...document.querySelectorAll('.strategy-picks input:checked')].map(input => input.value);
  const filtered = filterRows(evaluated, config, {query:$('search').value,strategies:selected});
  const sorted = sortRows(filtered, $('sortField').value, $('sortDirection').value);
  $('resultCount').textContent = `符合 ${filtered.length.toLocaleString('zh-TW')} 支`;
  $('tableLimit').textContent = sorted.length > 200 ? '顯示排序後前 200 支' : '';
  $('stockRows').innerHTML = sorted.slice(0,200).map((row,index) => `<tr>
    <td>${index+1}</td><td class="ticker">${escapeHtml(row.stock_id)}</td><td>${escapeHtml(row.stock_name)}</td>
    <td>${fmt(row.close,2)}</td><td><strong>${fmt(row.score_total,2)}</strong></td><td>${fmt(row.score_quality,2)}</td><td>${fmt(row.score_growth,2)}</td><td>${fmt(row.score_momentum,2)}</td>
    <td>${fmt(row.eps_ttm,2)}</td><td>${fmt(row.eps_yoy,1)}</td><td>${fmt(row.revenue_yoy,1)}</td><td>${fmt(row.roe,1)}</td><td>${fmt(row.gross_margin,1)}</td><td>${fmt(row.operating_margin,1)}</td>
    <td>${fmt(row.ma20,2)}</td><td>${fmt(row.ma60,2)}</td><td>${fmt(row.ma120,2)}</td><td>${fmt(row.data_completeness,1)}%</td>
    ${strategyKeys.map(key => `<td><span class="badge ${row[key]}">${labels[row[key]]}</span></td>`).join('')}</tr>`).join('');
}
function applyFilterSettings() {
  for (const key of Object.keys(config.filters)) {
    const value = number($(key).value);
    if (value === null) return;
    config.filters[key] = value;
  }
  saveSettings(config);
  render();
}
async function init() {
  try {
    const [settingsResponse,dataResponse] = await Promise.all([fetch('./config/strategies.json'),fetch('./data/latest.json')]);
    if (!settingsResponse.ok || !dataResponse.ok) throw new Error('資料檔載入失敗');
    defaults = await settingsResponse.json();
    rawRows = await dataResponse.json();
    config = loadSettings(defaults);
    evaluated = evaluateRows(rawRows,config);
    for (const [key,value] of Object.entries(config.filters)) $(key).value = value;
    for (const key of Object.keys(config.filters)) $(key).addEventListener('input',applyFilterSettings);
    $('search').addEventListener('input',render);
    document.querySelectorAll('.strategy-picks input').forEach(input => input.addEventListener('change',render));
    $('sortField').addEventListener('change',render);$('sortDirection').addEventListener('change',render);
    $('applyButton').addEventListener('click',applyFilterSettings);
    render();
  } catch(error) { $('dataNotice').textContent = `無法載入資料：${error.message}`; $('dataNotice').hidden = false; }
}
init();
