import test from 'node:test';
import assert from 'node:assert/strict';
import {annualPair,DEFAULTS,evaluateRow,evaluateRows,sortRows} from '../docs/eps_value_engine.mjs';

const eps = [
  {year:2024,eps:10,basis:'basic',scope:'consolidated',method:'issuer',verified_official:true},
  {year:2025,eps:12,basis:'basic',scope:'consolidated',method:'issuer',verified_official:true},
];
const prices = Array.from({length:30},(_,i)=>[`2026-09-${String(i+1).padStart(2,'0')}`,100]);
prices[28][1]=105;
prices[29][1]=99;
const row={stock_id:'2330',stock_name:'台積電',close:99,latest_date:prices.at(-1)[0],per:12,valuation_date:'2026-09-30'};

test('annual EPS uses the latest consecutive positive basic EPS with consistent scope',()=>{
  const result=annualPair(eps);
  assert.equal(result.previous.year,2024);
  assert.equal(result.current.year,2025);
  assert.equal(result.growth,20);
  assert.equal(result.scopeLabel,'合併');
  assert.equal(annualPair([...eps.slice(0,1),{...eps[1],scope:'standalone'}]).scopeLabel,null);
});

test('default strategy calculates monthly average, deviation and prior pullback',()=>{
  const result=evaluateRow(row,{annual_eps:eps,prices},{...DEFAULTS});
  assert.equal(result.status,'pass');
  assert.equal(result.epsGrowth,20);
  assert.equal(result.ma,100.2);
  assert.ok(result.deviation >= -3 && result.deviation <= 3);
  assert.equal(result.reason,'');
});

test('pullback threshold is inclusive at the configured percentage',()=>{
  const flat=prices.map(([day])=>[day,100]);
  const result=evaluateRow({...row,close:100},{annual_eps:eps,prices:flat},{...DEFAULTS,pullbackPct:0});
  assert.equal(result.status,'pass');
});

test('missing data is not treated as zero and condition toggles exclude disabled gates',()=>{
  const missing=evaluateRow({...row,per:null},{annual_eps:[],prices:[]},{...DEFAULTS});
  assert.equal(missing.status,'missing_data');
  assert.match(missing.reason,/年度基本 EPS/);
  const relaxed={...DEFAULTS,epsEnabled:false,perEnabled:false,deviationEnabled:false,pullbackEnabled:false};
  assert.equal(evaluateRow({...row,per:null},{annual_eps:[],prices:[]},relaxed).status,'pass');
});

test('negative EPS fails the positive EPS rule without inventing a growth rate',()=>{
  const nonPositive=[{...eps[0],eps:-2},{...eps[1],eps:-1}];
  const result=evaluateRow(row,{annual_eps:nonPositive,prices},{...DEFAULTS});
  assert.equal(result.status,'fail');
  assert.equal(result.epsGrowth,null);
  assert.match(result.reason,/兩年 EPS 須皆大於 0/);
  assert.doesNotMatch(result.reason,/EPS 成長率低於/);
});

test('unknown scope and quarterly fallback cannot pass even with growth disabled',()=>{
  for (const records of [eps.map(x=>({...x,scope:null})), eps.map(x=>({...x,verified_official:false}))]) {
    const result=evaluateRow(row,{annual_eps:records,prices},{...DEFAULTS,growthEnabled:false});
    assert.equal(result.status,'missing_data');
    assert.equal(result.epsGrowth,null);
  }
});

test('latest positive PER uses its own date and excludes values after the quote date',()=>{
  const aux={annual_eps:eps,prices,valuations:[{date:'2026-09-28',per:13},{date:'2026-10-01',per:8}]};
  const result=evaluateRow({...row,per:null},aux,{...DEFAULTS});
  assert.equal(result.per,13);
  assert.equal(result.valuationDate,'2026-09-28');
  assert.equal(result.status,'pass');
  assert.equal(evaluateRow({...row,valuation_date:null}, {annual_eps:eps,prices}, DEFAULTS).status,'missing_data');
});

test('missing trading-day close is not silently removed from the moving average window',()=>{
  const gaps=prices.map(x=>[...x]);
  gaps[20][1]=null;
  const result=evaluateRow(row,{annual_eps:eps,prices:gaps},DEFAULTS);
  assert.equal(result.ma,null);
  assert.equal(result.status,'missing_data');
});

test('monthly period, asymmetric bounds, pullback and rising-MA switches affect results',()=>{
  assert.equal(evaluateRow(row,{annual_eps:eps,prices},{...DEFAULTS,deviationMin:0}).status,'fail');
  assert.equal(evaluateRow(row,{annual_eps:eps,prices},{...DEFAULTS,maDays:120}).status,'missing_data');
  const flat=prices.map(([day])=>[day,100]);
  const flatRow={...row,close:100};
  assert.equal(evaluateRow(flatRow,{annual_eps:eps,prices:flat},{...DEFAULTS,pullbackEnabled:false}).status,'pass');
  assert.equal(evaluateRow(flatRow,{annual_eps:eps,prices:flat},{...DEFAULTS,pullbackEnabled:false,uptrendEnabled:true}).status,'fail');
});

test('supported sorting orders deviation, PER and EPS growth with missing values last',()=>{
  const records=[{...row,stock_id:'1',deviation:2,per:12,epsGrowth:10},
    {...row,stock_id:'2',deviation:-1,per:15,epsGrowth:30},
    {...row,stock_id:'3',deviation:null,per:null,epsGrowth:null}];
  assert.deepEqual(sortRows(records,'deviation','asc').map(x=>x.stock_id),['2','1','3']);
  assert.deepEqual(sortRows(records,'per','asc').map(x=>x.stock_id),['1','2','3']);
  assert.deepEqual(sortRows(records,'epsGrowth','desc').map(x=>x.stock_id),['2','1','3']);
  assert.equal(evaluateRows([row],{2330:{annual_eps:eps,prices}},{...DEFAULTS})[0].status,'pass');
});
