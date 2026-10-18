import test from 'node:test';
import assert from 'node:assert/strict';
import {DEFAULT_BACKTEST, MISSING_DATA_REASONS, parsePricesCsv, runBacktest,
  skippedDetailsToCsv, tradesToCsv, parsePriceFile} from '../docs/backtest_engine.mjs';

const day = (date, stock_id, open, high = open, low = open, close = open, volume = 1000000) =>
  ({date, stock_id, open, high, low, close, volume});
const base = overrides => ({...DEFAULT_BACKTEST, startDate:'2026-01-03', endDate:'2026-01-05',
  initialCapital:200000, maxPositions:1, maShort:1, maLong:2,
  useCloseAboveShort:false, useShortAboveLong:false, returnDays:1, minReturnPct:-100,
  volumeDays:1, minAvgVolumeShares:0, takeProfitPct:90, stopLossPct:90,
  maxHoldDays:20, feeRatePct:0, feeMinimum:0, sellTaxPct:0, slippagePct:0,
  ...overrides});
const info = {'1001':{name:'測試股',market:'TWSE'}};

test('cross-year parsing retains only requested warmup interval and counts all file rows',()=>{
  const header='date,stock_id,open,high,low,close,volume\n';
  const csv=header+'2025-12-30,1001,10,10,10,10,1000\n'+
    '2025-12-31,1001,11,11,11,11,1000\n2026-01-02,1001,12,12,12,12,1000\n';
  const parsed=parsePriceFile(csv,{start:'2025-12-31',end:'2026-01-02'});
  assert.equal(parsed.totalRows,3);
  assert.deepEqual(parsed.rows.map(r=>r.date),['2025-12-31','2026-01-02']);
  assert.deepEqual(parsePriceFile(csv).rows,parsePricesCsv(csv));
});

test('120 completed warmup sessions permit an opening buy on the first backtest session',()=>{
  const rows=[];
  for(let i=0;i<=120;i++) {
    const date=new Date(Date.UTC(2025,6,1+i)).toISOString().slice(0,10);
    rows.push(day(date,'1001',100+i));
  }
  const result=runBacktest(rows,base({startDate:rows[120].date,endDate:rows[120].date,
    initialCapital:1000000,maShort:20,maLong:120,useCloseAboveShort:true,useShortAboveLong:true,
    minReturnPct:0}),info);
  assert.equal(result.skipped.warmup_insufficient,0);
  assert.equal(result.openPositions[0].entry_date,rows[120].date);
  assert.equal(result.openPositions[0].entry_price,rows[120].open);
});

test('year boundary signals buy on the next stored market session',()=>{
  const rows=[day('2025-12-30','1001',100),day('2025-12-31','1001',101),
    day('2026-01-02','1001',102)];
  const result=runBacktest(rows,base({startDate:'2025-12-31',endDate:'2026-01-02'}),info);
  assert.equal(result.openPositions[0].entry_date,'2026-01-02');
  assert.equal(result.openPositions[0].entry_price,102);
});

test('signal uses only previous close and buys at next opening, with warmup',()=>{
  const rows=[day('2026-01-01','1001',100),day('2026-01-02','1001',100),
    day('2026-01-03','1001',125,130,120,125),day('2026-01-04','1001',70)];
  const result=runBacktest(rows,base({startDate:'2026-01-02',endDate:'2026-01-04'}),info);
  assert.equal(result.openPositions[0].entry_date,'2026-01-03');
  assert.equal(result.openPositions[0].entry_price,125);
  assert.equal(result.trades.length,0);
  assert.equal(result.equityCurve[0].equity,200000);
  assert.ok(result.skipped.warmup_insufficient >= 1);
});

test('overnight gap through stop sells at opening rather than stop threshold',()=>{
  const rows=[day('2026-01-01','1001',100),day('2026-01-02','1001',100),
    day('2026-01-03','1001',100),day('2026-01-04','1001',85,86,84,85)];
  const result=runBacktest(rows,base({stopLossPct:10,endDate:'2026-01-04'}),info);
  assert.equal(result.trades[0].exit_date,'2026-01-04');
  assert.equal(result.trades[0].exit_price,85);
  assert.equal(result.trades[0].exit_reason,'停損');
});

test('same daily bar touches both thresholds: stop wins, including entry day',()=>{
  const rows=[day('2026-01-01','1001',100),day('2026-01-02','1001',100),
    day('2026-01-03','1001',100,120,80,100)];
  const result=runBacktest(rows,base({stopLossPct:10,takeProfitPct:10,
    endDate:'2026-01-03'}),info);
  assert.equal(result.trades[0].exit_price,90);
  assert.equal(result.trades[0].exit_reason,'停損');
  assert.equal(result.trades[0].entry_date,result.trades[0].exit_date);
});

test('opening gap and fees shrink the planned buy to affordable whole lots',()=>{
  const rows=[day('2026-01-01','1001',10),day('2026-01-02','1001',10),
    day('2026-01-03','1001',20,21,19,20)];
  const result=runBacktest(rows,base({initialCapital:100000,feeRatePct:0.1425,
    feeMinimum:20,slippagePct:0.1,endDate:'2026-01-03'}),info);
  assert.equal(result.openPositions[0].shares,4000);
  assert.equal(result.skipped.cash_reduced,1);
  assert.ok(result.equityCurve.at(-1).cash >= 0);
});

test('buy and sell charges include slippage, two fees and sell tax',()=>{
  const rows=[day('2026-01-01','1001',100),day('2026-01-02','1001',100),
    day('2026-01-03','1001',100),day('2026-01-04','1001',100)];
  const result=runBacktest(rows,base({feeRatePct:0.1,feeMinimum:20,
    sellTaxPct:0.3,slippagePct:1,maxHoldDays:1,endDate:'2026-01-04'}),info);
  const trade=result.trades[0];
  assert.equal(trade.shares,1000);
  assert.equal(trade.entry_price,101);
  assert.equal(trade.exit_price,99);
  assert.equal(trade.entry_fee,101);
  assert.equal(trade.exit_fee,99);
  assert.equal(trade.sell_tax,297);
  assert.equal(trade.net_pnl,-2497);
  assert.equal(trade.exit_reason,'到期');
});

test('blocked stop persists and exits on next tradable opening',()=>{
  const rows=[day('2026-01-01','1001',100),day('2026-01-02','1001',100),
    day('2026-01-03','1001',100),day('2026-01-04','1001',90),
    day('2026-01-05','1001',95,100,94,98)];
  const result=runBacktest(rows,base({stopLossPct:10}),info);
  assert.equal(result.trades[0].exit_date,'2026-01-05');
  assert.equal(result.trades[0].exit_price,95);
  assert.equal(result.trades[0].exit_reason,'停損');
  assert.ok(result.skipped.unable_to_fill >= 1);
});

test('unfilled next-day buy expires instead of filling on a later day',()=>{
  const rows=[day('2026-01-01','1001',100),day('2026-01-02','1001',100),
    day('2026-01-03','1001',110,110,110,110,1),
    day('2026-01-04','1001',100,102,98,100)];
  const result=runBacktest(rows,base({minAvgVolumeShares:1000,
    endDate:'2026-01-04'}),info);
  assert.equal(result.trades.length,0);
  assert.equal(result.openPositions.length,0);
  assert.ok(result.skipped.unable_to_fill >= 1);
});

test('same-opening sale proceeds cannot fund another opening buy',()=>{
  const rows=[
    day('2026-01-01','1001',50),day('2026-01-01','1002',100),
    day('2026-01-02','1001',50),day('2026-01-02','1002',100,100,100,100,1),
    day('2026-01-03','1001',50),day('2026-01-03','1002',50,51,49,50),
    day('2026-01-04','1001',50),day('2026-01-04','1002',100,101,99,100),
  ];
  const result=runBacktest(rows,base({initialCapital:100000,maxPositions:2,
    minAvgVolumeShares:1000,maxHoldDays:1,endDate:'2026-01-04'}),
    {...info,'1002':{name:'候選股',market:'TWSE'}});
  assert.equal(result.trades.length,1);
  assert.equal(result.trades[0].stock_id,'1001');
  assert.equal(result.openPositions.length,0);
  assert.ok(result.skipped.insufficient_cash >= 1);
});

test('expired holding keeps its exit intent across a missing trading day',()=>{
  const rows=[
    day('2026-01-01','1001',100),day('2026-01-02','1001',100),
    day('2026-01-03','1001',100),day('2026-01-05','1001',100),
    day('2026-01-01','1002',10),day('2026-01-02','1002',10),
    day('2026-01-03','1002',10),day('2026-01-04','1002',10),day('2026-01-05','1002',10),
  ];
  const result=runBacktest(rows,base({maxHoldDays:1,endDate:'2026-01-05'}),
    {...info,'1002':{name:'其他股',market:'TWSE'}});
  assert.equal(result.trades[0].exit_date,'2026-01-05');
  assert.equal(result.trades[0].exit_reason,'到期');
  assert.ok(result.skipped.missing_data >= 1);
});

test('initial capital is included in maximum drawdown; no closed trade is not zero percent',()=>{
  const rows=[day('2026-01-01','1001',100),day('2026-01-02','1001',100),
    day('2026-01-03','1001',100,100,90,90)];
  const result=runBacktest(rows,base({endDate:'2026-01-03',maxPositions:2}),info);
  assert.equal(result.equityCurve[0].equity,200000);
  assert.equal(result.summary.maxDrawdownPct,5);
  assert.equal(result.summary.closedTrades,0);
  assert.equal(result.summary.winRatePct,null);
});

test('CSV has costs, reasons and safe escaping; malformed quote data fails',()=>{
  const csv=tradesToCsv([{stock_id:'1001',stock_name:'=danger',entry_date:'2026-01-01',
    exit_date:'2026-01-02',entry_price:10,exit_price:11,shares:1000,
    entry_gross:10000,entry_fee:20,exit_gross:11000,exit_fee:20,sell_tax:33,
    net_pnl:927,return_pct:9.25,exit_reason:'停利'}]);
  assert.match(csv,/exit_reason/);
  assert.match(csv,/'=danger/);
  assert.match(csv,/停利/);
  assert.equal(parsePricesCsv('date,stock_id,open,high,low,close,volume\n2026-01-01,1001,10,11,9,10,1000').length,1);
  assert.throws(()=>parsePricesCsv('date,stock_id,open,high,low,close,volume\n2026-01-01,1001,10,11,9,bad,1000'));
});

test('missing-data diagnostics distinguish current gaps, lookback gaps, short history and coverage',()=>{
  const cases = [
    {reason:'current_quote_missing',rows:[day('2026-01-01','1001',10),day('2026-01-02','1002',10),
      day('2026-01-03','1001',10)],config:{startDate:'2026-01-02',endDate:'2026-01-03'}},
    {reason:'lookback_gap',rows:[day('2026-01-01','1001',10),day('2026-01-02','1002',10),
      day('2026-01-03','1001',10),day('2026-01-04','1001',10)],
      config:{startDate:'2026-01-03',endDate:'2026-01-04',returnDays:2}},
    {reason:'history_too_short',rows:[day('2026-01-01','1002',10),day('2026-01-02','1001',10),
      day('2026-01-03','1001',10),day('2026-01-04','1001',10)],
      config:{startDate:'2026-01-03',endDate:'2026-01-04',returnDays:2}},
    {reason:'outside_coverage',rows:[day('2026-01-01','1002',10),day('2026-01-02','1001',10)],
      config:{startDate:'2026-01-01',endDate:'2026-01-02'}},
  ];
  for (const item of cases) {
    const result=runBacktest(item.rows,base(item.config),info);
    assert.ok(result.missingDiagnostics[item.reason].events > 0, item.reason);
    assert.ok(result.skipDetails.some(row=>row.reason===item.reason), item.reason);
    assert.ok(result.missingDiagnostics[item.reason].stockCount > 0, item.reason);
    assert.equal(Object.values(result.missingDiagnostics).reduce((sum,stat)=>sum+stat.events,0),
      result.skipped.missing_data, item.reason);
  }
  assert.equal(MISSING_DATA_REASONS.history_too_short,'歷史長度不足');
  const csv=skippedDetailsToCsv([{date:'2026-01-02',stock_id:'1001',reason:'current_quote_missing'}]);
  assert.match(csv,/"date","stock_id","reason"/);
  assert.match(csv,/2026-01-02/);
  assert.match(csv,/當日行情缺漏/);
});
