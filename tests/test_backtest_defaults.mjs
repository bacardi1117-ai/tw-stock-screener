import test from 'node:test';
import assert from 'node:assert/strict';
import {resolveBacktestSettings} from '../docs/backtest_settings.mjs';
import {DEFAULT_BACKTEST} from '../docs/backtest_engine.mjs';
const manifest={start:'2025-04-01',end:'2026-10-16',backtest_start:'2025-09-22',
  recent_year_start:'2025-10-17',legacy_default_period:{start:'2026-07-15',end:'2026-10-14'}};

test('new visitors use the most recent year from the actual manifest',()=>{
  const result=resolveBacktestSettings(null,manifest,DEFAULT_BACKTEST);
  assert.equal(result.startDate,'2025-10-17');
  assert.equal(result.endDate,'2026-10-16');
});
test('legacy saved default dates migrate once while custom numeric settings survive',()=>{
  const result=resolveBacktestSettings({startDate:'2026-07-15',endDate:'2026-10-14',
    initialCapital:1234567,maxPositions:3},manifest,DEFAULT_BACKTEST);
  assert.equal(result.startDate,'2025-10-17');
  assert.equal(result.endDate,'2026-10-16');
  assert.equal(result.initialCapital,1234567);
  assert.equal(result.maxPositions,3);
  assert.equal(result._dateDefaultsVersion,2);
});
test('other saved custom date intervals remain unchanged',()=>{
  const result=resolveBacktestSettings({startDate:'2026-01-02',endDate:'2026-09-30'},manifest,DEFAULT_BACKTEST);
  assert.equal(result.startDate,'2026-01-02');
  assert.equal(result.endDate,'2026-09-30');
});
test('after migration an intentionally chosen original interval is preserved',()=>{
  const result=resolveBacktestSettings({startDate:'2026-07-15',endDate:'2026-10-14',
    _dateDefaultsVersion:2},manifest,DEFAULT_BACKTEST);
  assert.equal(result.startDate,'2026-07-15');
  assert.equal(result.endDate,'2026-10-14');
});
