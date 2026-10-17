import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {evaluateRows,filterRows,sortRows} from '../docs/engine.mjs';
import {clone,loadSettings,saveSettings,restoreDefault,exportText,parseImport,STORAGE_KEY,withCoverageMetadata} from '../docs/settings_state.mjs';

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
