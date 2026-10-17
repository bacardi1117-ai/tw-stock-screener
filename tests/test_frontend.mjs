import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {evaluateRows,filterRows,sortRows} from '../docs/engine.mjs';
import {clone,loadSettings,saveSettings,restoreDefault,exportText,parseImport,STORAGE_KEY,withCoverageMetadata} from '../docs/settings_state.mjs';
import {FIELD_LABELS,OPERATOR_LABELS,RULE_LABELS,STRATEGY_LABELS} from '../docs/labels.mjs';
import {qgmMaximumPoints,weightsMatchMaximum} from '../docs/settings_metrics.mjs';

const defaults=JSON.parse(fs.readFileSync(new URL('../config/strategies.json',import.meta.url),'utf8'));
const rows=JSON.parse(fs.readFileSync(new URL('./strategy_fixture.json',import.meta.url),'utf8'));
function storage() {const data=new Map();return {getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value),removeItem:key=>data.delete(key),data};}

test('number input changes the matching count',()=>{
  const config=clone(defaults);
  assert.equal(evaluateRows(rows,config).filter(row=>row.strategy_a==='pass').length,1);
  config.strategy_a.conditions.revenue_yoy.value=31;
  assert.equal(evaluateRows(rows,config).filter(row=>row.strategy_a==='pass').length,0);
});
test('checkbox disables a condition',()=>{
  const config=clone(defaults);
  config.strategy_a.conditions.revenue_yoy.value=999;
  assert.equal(evaluateRows(rows,config)[0].strategy_a,'fail');
  config.strategy_a.conditions.revenue_yoy.enabled=false;
  assert.equal(evaluateRows(rows,config)[0].strategy_a,'pass');
});
test('restore defaults, localStorage, JSON export and import',()=>{
  const memory=storage(), modified=clone(defaults);
  modified.strategy_a.conditions.roe.value=19;
  saveSettings(modified,memory);
  assert.equal(loadSettings(defaults,memory).strategy_a.conditions.roe.value,19);
  const imported=parseImport(exportText(modified));
  assert.equal(imported.strategy_a.conditions.roe.value,19);
  const reset=restoreDefault(defaults,memory);
  assert.equal(reset.strategy_a.conditions.roe.value,10);
  assert.equal(memory.getItem(STORAGE_KEY),null);
});
test('old localStorage and JSON exports gain default enabled flags without changing keys',()=>{
  const memory=storage(), legacy=clone(defaults);
  for (const category of ['quality','growth','momentum']) for (const rule of legacy.qgm[category]) delete rule.enabled;
  memory.setItem(STORAGE_KEY,JSON.stringify(legacy));
  const loaded=loadSettings(defaults,memory);
  assert.ok(['quality','growth','momentum'].every(category=>loaded.qgm[category].every(rule=>rule.enabled===true)));
  const imported=parseImport(JSON.stringify(legacy),defaults);
  assert.ok(imported.qgm.quality.every(rule=>rule.enabled===true));
  for (const category of ['quality','growth','momentum']) {
    assert.deepEqual(loaded.qgm[category].map(rule=>rule.id),defaults.qgm[category].map(rule=>rule.id));
    assert.deepEqual(loaded.qgm[category].map(rule=>rule.field),defaults.qgm[category].map(rule=>rule.field));
  }
});
test('Chinese display mapping retains internal field keys and units',()=>{
  assert.equal(FIELD_LABELS.revenue_yoy.label,'最新月營收年增率');
  assert.equal(FIELD_LABELS.gross_margin_yoy.unit,'百分點');
  assert.equal(FIELD_LABELS.eps_ttm.unit,'元');
  assert.equal(RULE_LABELS.eps_stability,'EPS 穩定度');
  assert.equal(OPERATOR_LABELS.gte,'至少');
  assert.equal(STRATEGY_LABELS.strategy_e,'股息成長');
  assert.ok(defaults.qgm.growth.some(rule=>rule.field==='revenue_yoy'));
});
test('QGM factor toggles default on and maximum scores match category weights',()=>{
  assert.deepEqual(qgmMaximumPoints(defaults.qgm),{quality:40,growth:35,momentum:25});
  assert.deepEqual(weightsMatchMaximum(defaults.qgm),{quality:true,growth:true,momentum:true});
  const changed=clone(defaults);
  changed.qgm.quality[0].enabled=false;
  assert.equal(qgmMaximumPoints(changed.qgm).quality,30);
  assert.equal(weightsMatchMaximum(changed.qgm).quality,false);
  assert.equal(qgmMaximumPoints(defaults.qgm).quality,40);
});
test('search, strategy filter and sorting',()=>{
  const scored=evaluateRows(rows,defaults);
  assert.equal(filterRows(scored,defaults,{query:'完整標的'}).length,1);
  assert.equal(filterRows(scored,defaults,{strategies:['strategy_a']}).length,1);
  assert.equal(sortRows(scored,'score_total','asc')[0].stock_id,'1002');
  assert.equal(sortRows(scored,'score_total','desc')[0].stock_id,'1001');
});
test('missing PER never passes and invalid QGM weights are rejected',()=>{
  const scored=evaluateRows(rows,defaults);
  assert.equal(scored[1].strategy_a,'missing_data');
  const config=clone(defaults);config.qgm.quality_weight=41;
  assert.throws(()=>parseImport(JSON.stringify(config)),/100/);
});
test('download coverage metadata cannot be changed by a browser import',()=>{
  const imported=clone(defaults);
  imported.universe.min_price=30;
  imported.universe.downloaded_min_price=20;
  const current=withCoverageMetadata(imported,defaults);
  assert.equal(current.universe.min_price,30);
  assert.equal(current.universe.downloaded_min_price,50);
});
