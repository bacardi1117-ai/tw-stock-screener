import {evaluateRows, filterRows, strategyKeys, number} from './engine.mjs';
import {clone, loadSettings, saveSettings, restoreDefault, exportText, parseImport, withCoverageMetadata} from './settings_state.mjs';

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
let defaults, config, rows = [];

function input(label,path,value,{checkbox=false,step='any'}={}) {
  return `<label>${esc(label)}<input data-path="${esc(path)}" type="${checkbox?'checkbox':'number'}" ${checkbox ? (value?'checked':'') : `step="${step}" value="${esc(value)}"`}></label>`;
}
function conditionCard(key,condition,path) {
  const valueInput = 'right' in condition ? `<small>比較欄位：${esc(condition.field)} ＞ ${esc(condition.right)}</small>` : input('門檻',`${path}.value`,condition.value);
  return `<div class="setting-card"><h3>${esc(condition.label)}</h3><div class="toggle-row">${input('啟用條件',`${path}.enabled`,condition.enabled,{checkbox:true})}</div>${valueInput}</div>`;
}
function qgmRule(rule,path) {
  const description = rule.kind === 'tiers' ? `${esc(rule.field)} · ${rule.direction==='min'?'至少':'不高於'}` :
    rule.kind === 'fields' ? `${esc(rule.left)} ${esc(rule.op)} ${esc(rule.right)}` : `${esc(rule.field)} ${esc(rule.op)}`;
  const controls = rule.kind === 'tiers' ? `<div class="tier-grid">${rule.tiers.map((tier,i) => `${input('門檻',`${path}.tiers.${i}.value`,tier.value)}${input('分數',`${path}.tiers.${i}.points`,tier.points)}`).join('')}</div>` :
    `${rule.kind === 'compare' ? input('門檻',`${path}.value`,rule.value) : ''}${input('分數',`${path}.points`,rule.points)}`;
  return `<div class="setting-card"><h3>${esc(rule.id)}</h3><small>${description}</small>${controls}</div>`;
}
function section(eyebrow,title,content,note='') {
  return `<section class="panel"><div class="panel-head"><div><p class="eyebrow">${eyebrow}</p><h2>${esc(title)}</h2></div>${note?`<span class="section-note">${esc(note)}</span>`:''}</div>${content}</section>`;
}
function renderSections() {
  const universe = `<div class="setting-grid"><div class="setting-card">${input('最低股價', 'universe.min_price', config.universe.min_price)}</div><div class="setting-card">${input('排除金融股','universe.exclude_financials',config.universe.exclude_financials,{checkbox:true})}</div><div class="setting-card">${input('最低資料完整度 (%)','filters.data_completeness_min',config.filters.data_completeness_min)}</div></div>`;
  const weights = `<div class="setting-grid">${['quality','growth','momentum'].map(name=>`<div class="setting-card">${input(`${name.toUpperCase()} 權重`, `qgm.${name}_weight`, config.qgm[`${name}_weight`])}</div>`).join('')}</div><p id="weightTotal" class="weight-total"></p>`;
  const qgm = weights + ['quality','growth','momentum'].map(name => `<h3>${name.toUpperCase()} 子項</h3><div class="setting-grid">${config.qgm[name].map((rule,i)=>qgmRule(rule,`qgm.${name}.${i}`)).join('')}</div>`).join('');
  const filterControls = `<div class="setting-grid">${['score_total_min','score_quality_min','score_growth_min','score_momentum_min'].map(name=>`<div class="setting-card">${input(name,`filters.${name}`,config.filters[name])}</div>`).join('')}</div>`;
  $('settingsSections').innerHTML = section('UNIVERSE','資料母體',universe,`目前基本面下載母體：非金融且股價至少 ${config.universe.downloaded_min_price} 元`) +
    section('QGM','QGM 權重與子項',qgm,'權重總和必須為 100') + section('SCORE FILTERS','分數篩選',filterControls) +
    strategyKeys.map((key,i)=>section(`STRATEGY ${'ABCDE'[i]}`,`策略 ${'ABCDE'[i]} · ${config[key].label}`,
      `<div class="setting-card toggle-row">${input('啟用策略',`${key}.enabled`,config[key].enabled,{checkbox:true})}</div><div class="setting-grid">${Object.entries(config[key].conditions).map(([id,condition])=>conditionCard(id,condition,`${key}.conditions.${id}`)).join('')}</div>`,
      config[key].unavailable_message ?? '')).join('');
  $('settingsSections').querySelectorAll('input[data-path]').forEach(element => element.addEventListener('input',onInput));
  showWeightTotal();
}
function setPath(path,value) {
  const parts=path.split('.'); let target=config;
  for (const part of parts.slice(0,-1)) target=target[part];
  target[parts.at(-1)]=value;
}
function showWeightTotal() {
  const sum=['quality','growth','momentum'].reduce((total,name)=>total+Number(config.qgm[`${name}_weight`] || 0),0);
  const element=$('weightTotal'); element.textContent=`權重總和：${Math.round(sum*100)/100} / 100`;
  element.classList.toggle('invalid',Math.abs(sum-100)>1e-8);
  return Math.abs(sum-100)<=1e-8;
}
function showNotice() {
  const messages=['策略 C：估值資料待補','策略 D：法人資料待補','策略 E：股利資料待補'];
  if (config.universe.min_price < config.universe.downloaded_min_price ||
      (!config.universe.exclude_financials && config.universe.downloaded_exclude_financials))
    messages.unshift('此設定超出目前已下載的基本面資料母體，需重新執行資料更新才能完整套用。');
  $('dataNotice').textContent=messages.join('　｜　'); $('dataNotice').hidden=false;
}
function recalculate() {
  showNotice();
  if (!showWeightTotal()) { $('validation').textContent='QGM 三項權重總和必須等於 100。可按「自動正規化到 100」。'; $('validation').hidden=false; return; }
  try {
    const scored=evaluateRows(rows,config);
    const mother=filterRows(scored,config);
    $('liveCounts').innerHTML=strategyKeys.map((key,i)=>`<div class="card"><strong>策略 ${'ABCDE'[i]} · ${esc(config[key].label)}</strong><div class="count">${mother.filter(row=>row[key]==='pass').length}</div><small>${mother.every(row=>row[key]==='unavailable') ? esc(config[key].unavailable_message??'尚不可用') : `母體 ${mother.length} 支`}</small></div>`).join('');
    $('validation').hidden=true;
  } catch(error) { $('validation').textContent=error.message; $('validation').hidden=false; }
}
function onInput(event) {
  const element=event.currentTarget;
  const value=element.type==='checkbox' ? element.checked : number(element.value);
  if (value===null) { $('validation').textContent='請輸入有效數值。'; $('validation').hidden=false; return; }
  setPath(element.dataset.path,value);
  recalculate();
  if ($('validation').hidden) { saveSettings(config); $('saveMessage').textContent='已儲存於此瀏覽器'; }
}
function normalizeWeights() {
  const names=['quality','growth','momentum'];
  const values=names.map(name=>Math.max(0,Number(config.qgm[`${name}_weight`])||0));
  const total=values.reduce((a,b)=>a+b,0);
  const normalized=total ? values.map(value=>value/total*100) : [100/3,100/3,100/3];
  let assigned=0;
  names.forEach((name,i)=>{ const value=i===2 ? 100-assigned : Math.round(normalized[i]*100)/100; config.qgm[`${name}_weight`]=value; assigned+=value; });
  renderSections(); recalculate(); saveSettings(config); $('saveMessage').textContent='已正規化並儲存';
}
async function init() {
  try {
    const [configResponse,dataResponse]=await Promise.all([fetch('./config/strategies.json'),fetch('./data/latest.json')]);
    if (!configResponse.ok || !dataResponse.ok) throw new Error('資料檔載入失敗');
    defaults=await configResponse.json(); rows=await dataResponse.json(); config=loadSettings(defaults);
    renderSections(); recalculate();
    $('applyButton').addEventListener('click',()=>{recalculate();if ($('validation').hidden){saveSettings(config);$('saveMessage').textContent='已套用並儲存於此瀏覽器';}});
    $('normalizeButton').addEventListener('click',normalizeWeights);
    $('resetButton').addEventListener('click',()=>{config=restoreDefault(defaults);renderSections();recalculate();$('saveMessage').textContent='已恢復預設值';});
    $('exportButton').addEventListener('click',()=>{try{const blob=new Blob([exportText(config)],{type:'application/json'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='strategies.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){$('validation').textContent=error.message;$('validation').hidden=false;}});
    $('importFile').addEventListener('change',async event=>{const file=event.target.files?.[0];if(!file)return;try{config=withCoverageMetadata(clone(parseImport(await file.text())),defaults);saveSettings(config);renderSections();recalculate();$('saveMessage').textContent='已匯入並儲存於此瀏覽器';}catch(error){$('validation').textContent=`匯入失敗：${error.message}`;$('validation').hidden=false;}event.target.value='';});
  } catch(error) { $('validation').textContent=`無法載入資料：${error.message}`; $('validation').hidden=false; }
}
init();
