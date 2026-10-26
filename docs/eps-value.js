import {DEFAULTS, STORAGE_KEY, evaluateRows, sortRows, number} from './eps_value_engine.mjs';

const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const fmt = (value, digits=2, suffix='') => number(value) === null ? '—' : `${Number(value).toLocaleString('zh-TW',{maximumFractionDigits:digits})}${suffix}`;
const statusLabel = {pass:'符合',fail:'未符合',missing_data:'無法判斷'};
const fields = {
  epsEnabled:'epsEnabled',positiveRequired:'positiveRequired',growthEnabled:'growthEnabled',minGrowth:'minGrowth',
  perEnabled:'perEnabled',perMin:'perMin',perMax:'perMax',maDays:'maDays',deviationEnabled:'deviationEnabled',
  deviationMin:'deviationMin',deviationMax:'deviationMax',pullbackEnabled:'pullbackEnabled',pullbackDays:'pullbackDays',
  pullbackPct:'pullbackPct',uptrendEnabled:'uptrendEnabled',uptrendDays:'uptrendDays',sortField:'sortField',sortDirection:'sortDirection',
};
let config = {...DEFAULTS}, rows = [], auxiliary = {}, evaluated = [];

function readSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    return {...DEFAULTS, ...saved};
  } catch { return {...DEFAULTS}; }
}
function saveSettings() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  $('saveMessage').textContent = '設定已保存在此瀏覽器';
}
function syncSettings() {
  for (const [id,key] of Object.entries(fields)) {
    const element = $(id);
    if (key.endsWith('Enabled') || key === 'positiveRequired' || key === 'deviationEnabled' || key === 'pullbackEnabled' || key === 'uptrendEnabled') element.checked = Boolean(config[key]);
    else element.value = config[key];
  }
}
function bindSettings() {
  syncSettings();
  for (const [id,key] of Object.entries(fields)) {
    const element = $(id);
    element.addEventListener('input', () => {
      config[key] = element.type === 'checkbox' ? element.checked : (element.tagName === 'SELECT' ? element.value : number(element.value));
      refresh();
    });
  }
}
function validate() {
  for (const key of ['minGrowth','perMin','perMax','deviationMin','deviationMax','pullbackPct']) {
    if (number(config[key]) === null) return '請輸入有效的數值門檻。';
  }
  const integerRanges = [['maDays',2,120],['pullbackDays',1,60],['uptrendDays',1,60]];
  for (const [key,min,max] of integerRanges) {
    if (!Number.isInteger(config[key]) || config[key] < min || config[key] > max) return `${key} 必須介於 ${min} 到 ${max} 個交易日。`;
  }
  if (config.perMin < 0 || config.perMax <= 0 || config.perMax <= config.perMin) return '本益比上限必須大於下限，且上限大於 0。';
  if (config.deviationMin < -100 || config.deviationMax < config.deviationMin) return '乖離率上下界不正確。';
  if (config.minGrowth < -100 || config.pullbackPct < 0) return 'EPS 成長門檻需至少 -100%，回落百分比不得小於 0。';
  return null;
}
function render() {
  const statusCount = evaluated.filter(row => row.status === 'pass').length;
  const insufficient = evaluated.filter(row => row.status === 'missing_data').length;
  $('passCount').textContent = statusCount.toLocaleString('zh-TW');
  $('resultSummary').textContent = `母體 ${evaluated.length.toLocaleString('zh-TW')} 支　｜　符合 ${statusCount.toLocaleString('zh-TW')} 支　｜　無法判斷 ${insufficient.toLocaleString('zh-TW')} 支`;
  const sorted = sortRows(evaluated, config.sortField, config.sortDirection);
  $('stockRows').innerHTML = sorted.map(row => {
    const epsDisplay = row.previousEps && row.currentEps
      ? `${row.previousEps.year}：${fmt(row.previousEps.eps)} 元<br>${row.currentEps.year}：${fmt(row.currentEps.eps)} 元`
      : '—';
    const epsDates = row.previousEps && row.currentEps
      ? `<small>${escapeHtml(row.previousEps.period_end)} ／ ${escapeHtml(row.currentEps.period_end)}</small>` : '<small>年度 EPS 資料不足</small>';
    const perDate = row.valuationDate ? escapeHtml(row.valuationDate) : '日期缺漏';
    const reason = row.reason || (row.epsReason || '—');
    return `<tr>
      <td><span class="badge ${row.status}">${statusLabel[row.status]}</span></td>
      <td class="eps-stock"><strong>${escapeHtml(row.stock_id)}</strong> ${escapeHtml(row.stock_name)}</td>
      <td>${fmt(row.close,2,' 元')}<br><small>${escapeHtml(row.closeDate || '日期缺漏')}</small></td>
      <td>${fmt(row.ma,2,' 元')}<br><small>${config.maDays} 日</small></td>
      <td>${fmt(row.deviation,2,'%')}</td>
      <td>${epsDisplay}<br>${epsDates}</td>
      <td>${fmt(row.epsGrowth,2,'%')}</td>
      <td>${escapeHtml(row.epsScopeLabel || '無法確認')}<br><small>${row.currentEps?.verified_official && row.previousEps?.verified_official ? '官方已驗證年度值' : (row.currentEps && row.previousEps ? '季度加總／未驗證，不用於篩選' : '—')}</small></td>
      <td>${fmt(row.per,2)}<br><small>${perDate} · TWSE / TPEx 官方 PER</small></td>
      <td class="eps-reason">${escapeHtml(reason)}</td>
    </tr>`;
  }).join('');
}
function refresh() {
  const error = validate();
  if (error) { $('validation').textContent = error; $('validation').hidden = false; return; }
  $('validation').hidden = true;
  evaluated = evaluateRows(rows, auxiliary, config);
  render();
  saveSettings();
}
async function init() {
  try {
    const [rowsResponse, dataResponse] = await Promise.all([fetch('./data/latest.json'), fetch('./data/eps_value.json')]);
    if (!rowsResponse.ok || !dataResponse.ok) throw new Error('策略資料載入失敗');
    rows = await rowsResponse.json();
    const payload = await dataResponse.json();
    auxiliary = Object.fromEntries(Object.entries(payload.stocks || {}).map(([sid, item]) => [sid, {
      annual_eps: item.annual_eps || [],
      valuations: item.valuations || [],
      prices: (item.closes || []).map((close, index) => [payload.dates[index], close]),
    }]));
    config = readSettings();
    bindSettings();
    $('sortField').value = config.sortField;
    $('sortDirection').value = config.sortDirection;
    $('sortField').addEventListener('change', event => { config.sortField = event.target.value; refresh(); });
    $('sortDirection').addEventListener('change', event => { config.sortDirection = event.target.value; refresh(); });
    $('resetButton').addEventListener('click', () => {
      config = {...DEFAULTS};
      localStorage.removeItem(STORAGE_KEY);
      syncSettings();
      $('sortField').value = config.sortField;
      $('sortDirection').value = config.sortDirection;
      refresh();
      $('saveMessage').textContent = '已恢復第一版預設值';
    });
    const dates = rows.map(row => row.latest_date).filter(Boolean).sort();
    $('dataNotice').textContent = `快照行情日期：${dates.at(-1) || '無'}。PER 使用現有資料中最新有效交易所數值；EPS 須有官方年度值且兩年合併／個體口徑一致，缺少證據標示無法判斷。`;
    $('dataNotice').hidden = false;
    refresh();
  } catch (error) {
    $('validation').textContent = `無法載入策略資料：${error.message}`;
    $('validation').hidden = false;
  }
}
init();
