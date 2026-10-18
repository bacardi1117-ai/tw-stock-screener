import {evaluateRows, filterRows, sortRows, strategyKeys, number} from './engine.mjs';
import {loadSettings, saveSettings} from './settings_state.mjs';
import {FIELD_LABELS, fieldLabel, strategyLabel} from './labels.mjs';

const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const fmt = (value, digits=1, unit='') => number(value) === null ? '—' : `${Number(value).toLocaleString('zh-TW',{maximumFractionDigits:digits,minimumFractionDigits:0})}${unit}`;
const labels = {pass:'符合',fail:'未符合',missing_data:'資料不足',unavailable:'尚不可用'};
let defaults, config, rawRows = [], evaluated = [];

function applyDisplayLabels() {
  document.querySelectorAll('[data-field]').forEach(element => {
    const key=element.dataset.field;
    const unit=FIELD_LABELS[key]?.unit;
    const label=`${fieldLabel(key,key)}${unit?`（${unit}）`:''}`;
    if (element.tagName === 'LABEL') element.insertBefore(document.createTextNode(`${label} `),element.firstChild);
    else element.textContent=label;
  });
  document.querySelectorAll('option[value]').forEach(option => {
    if (option.value in FIELD_LABELS) option.textContent=fieldLabel(option.value,option.value);
  });
  document.querySelectorAll('[data-strategy]').forEach(element=>{element.textContent=strategyLabel(element.dataset.strategy);});
  document.querySelectorAll('.strategy-picks label').forEach(label=>{label.setAttribute('aria-label',label.querySelector('span')?.textContent??'策略');});
}

function showNotice() {
  const dates = rawRows.map(row => row.institutional_data_date).filter(Boolean);
  const latest = dates.length ? dates.sort().at(-1) : '尚未取得';
  const messages = ['缺少的估值或股利資料會保留空值，並標示為資料不足',
    `策略 D 法人資料截止日：${latest}；外資含陸資、不含外資自營商，單位為股。資料不足原因見股票清單。`];
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
    return `<div class="card"><strong>${escapeHtml(strategyLabel(key))}</strong><div class="count">${count}</div><small>${unavailable ? config[key].unavailable_message ?? '資料尚不可用' : '支符合目前條件'}</small></div>`;
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
    <td>${fmt(row.close,2,' 元')}</td><td><strong>${fmt(row.score_total,2,' 分')}</strong></td><td>${fmt(row.score_quality,2,' 分')}</td><td>${fmt(row.score_growth,2,' 分')}</td><td>${fmt(row.score_momentum,2,' 分')}</td>
    <td>${fmt(row.eps_ttm,2,' 元')}</td><td>${fmt(row.eps_yoy,1,'%')}</td><td>${fmt(row.revenue_yoy,1,'%')}</td><td>${fmt(row.roe,1,'%')}</td><td>${fmt(row.gross_margin,1,'%')}</td><td>${fmt(row.operating_margin,1,'%')}</td><td>${fmt(row.per,1)}</td><td>${fmt(row.pbr,2)}</td><td>${fmt(row.dividend_yield,2,'%')}</td><td>${fmt(row.cash_dividend_latest,2,' 元')}</td><td>${fmt(row.payout_ratio,1,'%')}</td><td>${fmt(row.dividend_years_5,0)} / ${fmt(row.dividend_history_years_available,0,' 年')}</td>
    <td>${fmt(row.ma20,2,' 元')}</td><td>${fmt(row.ma60,2,' 元')}</td><td>${fmt(row.ma120,2,' 元')}</td>
    <td>${fmt(row.foreign_plus_trust_20d,0,' 股')}</td><td>${fmt(row.trust_10d,0,' 股')}</td>
    <td>${escapeHtml(row.institutional_data_date || '—')}</td><td>${escapeHtml(row.strategy_d_missing_reason || '完整')}</td>
    <td>${fmt(row.data_completeness,1,'%')}</td>
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
    applyDisplayLabels();
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
