// Local, reproducible baseline/year validation. Does not fetch or publish data.
import fs from 'node:fs';
import crypto from 'node:crypto';
import {parsePriceFile,runBacktest} from '../docs/backtest_engine.mjs';

const manifest=JSON.parse(fs.readFileSync('docs/data/backtest/manifest.json','utf8'));
const baseline=JSON.parse(fs.readFileSync('tests/fixtures/backtest_expansion_baseline.json','utf8'));
const hash=trades=>crypto.createHash('sha256').update(JSON.stringify(trades)).digest('hex');
const initial=baseline.config;
const results={baseline:baseline.summary,baselineTradeHash:hash(baseline.trades)};
for (const [name,config] of Object.entries({
  original:initial,
  recentYear:{...initial,startDate:manifest.recent_year_start,endDate:manifest.end},
  ma120:{...initial,startDate:manifest.recent_year_start,endDate:manifest.end,maLong:120},
})) {
  global.gc?.();
  const start=performance.now();
  const first=manifest.trading_dates.findIndex(d=>d>=config.startDate);
  const warmup=Math.max(config.maLong,config.maShort,config.returnDays+1,config.volumeDays)+1;
  const earliest=manifest.trading_dates[Math.max(0,first-warmup)];
  const rows=[];let bytes=0;
  for (const year of manifest.years.filter(y=>y.end>=earliest&&y.start<=config.endDate)) {
    const buffer=fs.readFileSync('docs/data/backtest/'+year.file);
    if (crypto.createHash('sha256').update(buffer).digest('hex')!==year.sha256) throw new Error('Checksum mismatch');
    const parsed=parsePriceFile(buffer.toString('utf8'),{start:earliest,end:config.endDate});
    if(parsed.totalRows!==year.rows)throw new Error('Row count mismatch');
    for(const row of parsed.rows)rows.push(row);
    bytes+=year.compressed_bytes;
  }
  const parsedMs=performance.now()-start;
  const result=runBacktest(rows,config,manifest.stocks);
  const round2=n=>Math.round((n+Number.EPSILON)*100)/100;
  const unrealized=result.openPositions.reduce((sum,p)=>{
    const gross=round2(p.shares*p.entry_price);
    const fee=round2(Math.max(gross*config.feeRatePct/100,config.feeMinimum));
    return sum+p.shares*p.last_price-gross-fee;
  },0);
  const realized=result.trades.reduce((sum,t)=>sum+t.net_pnl,0);
  const identity=initial.initialCapital+realized+unrealized;
  if(Math.abs(identity-result.summary.finalEquity)>.011)throw new Error('Account identity mismatch');
  results[name]={config,summary:result.summary,effectiveStart:result.effectiveStart,effectiveEnd:result.effectiveEnd,
    tradingDays:result.tradingDays,tradeHash:hash(result.trades),unrealized,realized,accountIdentity:identity,
    openPositions:result.openPositions,skipped:result.skipped,missingDiagnostics:result.missingDiagnostics,
    retainedRows:rows.length,downloadBytes:bytes,parseMs:parsedMs,totalMs:performance.now()-start,
    heapUsedMiB:process.memoryUsage().heapUsed/1048576,maxRssMiB:process.resourceUsage().maxRSS/1024};
  if(name==='original') {
    results.original.tradesIdentical=hash(result.trades)===hash(baseline.trades);
    results.original.summaryIdentical=JSON.stringify(result.summary)===JSON.stringify(baseline.summary);
    const key=t=>[t.stock_id,t.entry_date,t.exit_date,t.shares,t.net_pnl].join('|');
    const before=new Set(baseline.trades.map(key)),after=new Set(result.trades.map(key));
    results.original.addedOrChangedTrades=result.trades.filter(t=>!before.has(key(t)));
    results.original.removedOrChangedTrades=baseline.trades.filter(t=>!after.has(key(t)));
    results.original.firstEquityDifference=result.equityCurve.find((p,i)=>
      p.date!==baseline.equityCurve[i]?.date||p.equity!==baseline.equityCurve[i]?.equity)??null;
  }
  fs.writeFileSync('data/state/backtest_expansion_'+name+'.json',JSON.stringify(result));
  console.log(name,JSON.stringify(results[name]));
}
fs.writeFileSync('data/state/backtest_expansion_validation.json',JSON.stringify(results,null,2));
