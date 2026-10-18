"""Offline cache recovery tests, isolated from the production batch CLI."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from repair_history_cache import repair_from_cache
from historical_coverage import DATASETS

INCOME = [dict(date=f"{y}-{d}", type="EPS", value=2) for y in (2023,2024,2025)
          for d in ("03-31","06-30","09-30","12-31")]
FLOWS = [dict(date=f"{y}-12-31", type="CashFlowsFromOperatingActivities", value=100)
         for y in (2023,2024,2025)]
def divs():
    return [dict(year=f"{y}年", CashEarningsDistribution=1, CashStatutorySurplus=0,
                 StockEarningsDistribution=0, StockStatutorySurplus=0) for y in range(110,115)]

class CacheRepairTests(unittest.TestCase):
    def root(self):
        temp=tempfile.TemporaryDirectory(dir=ROOT); self.addCleanup(temp.cleanup)
        root=Path(temp.name); (root/'data/state').mkdir(parents=True)
        pd.DataFrame([dict(stock_id=str(1000+i),stock_name='Sample',eligible=i<3,market='TWSE')
                      for i in range(4)]).to_csv(root/'data/state/fundamentals_universe.csv',index=False)
        return root
    def test_cache_repair_never_requests_skips_completed_and_preserves_last_api_run(self):
        root=self.root(); cache=root/'data/.historical_coverage';cache.mkdir(parents=True)
        for dataset in DATASETS:
            payload=INCOME if dataset.endswith('FinancialStatements') else FLOWS if dataset.endswith('CashFlowsStatement') else divs()
            (cache/f'1000_{dataset}.json').write_text(json.dumps(payload),encoding='utf8')
        entries={'1000':dict(status='failed',failure_reason='parse_error',error_type='TypeError',last_attempt_at='original-time'),
                 '1001':dict(status='completed',failure_reason=None),
                 '1002':dict(status='failed',failure_reason='parse_error'),
                 '1003':dict(status='failed',failure_reason='parse_error')}
        state=dict(stocks=entries,completed_count=1,remaining_count=2,failed_count=2,retryable_count=0,
                   attempted=60,completed=42,failed=18,last_run_api_calls=180,updated_at='old-time')
        progress=root/'data/state/history_progress.json';progress.write_text(json.dumps(state),encoding='utf8')
        with patch('requests.sessions.Session.request',side_effect=AssertionError('no API')), \
             patch('history_batch.FinMindClient',side_effect=AssertionError('no client')):
            before=progress.read_bytes();dry=repair_from_cache(root)
            self.assertEqual(progress.read_bytes(),before)
            self.assertEqual(dry['target_count'],2)
            result=repair_from_cache(root,apply=True)
        after=json.loads(progress.read_text(encoding='utf8'))
        self.assertEqual((result['repaired_count'],result['completed_from_cache'],result['api_calls']),(1,1,0))
        self.assertEqual((after['completed_count'],after['retryable_count'],after['remaining_count']),(2,1,1))
        self.assertEqual(after['stocks']['1001'],entries['1001'])
        self.assertEqual(after['stocks']['1003'],entries['1003'])
        self.assertEqual(after['stocks']['1000']['last_attempt_at'],'original-time')
        self.assertEqual(after['last_run_api_calls'],180)
        self.assertEqual(after['attempted'],60)
        self.assertTrue(after['stocks']['1002']['cache_repair_missing_datasets'])
        backup=root/result['backup_directory']/'history_progress.json'
        self.assertEqual(backup.read_bytes(),before)
    def test_cache_repair_busy_lock_does_not_read_or_write_progress(self):
        root=self.root(); path=root/'data/state/history_progress.json'
        path.write_text('unchanged invalid JSON',encoding='utf8')
        with patch('repair_history_cache.ApiBudget._lock',side_effect=OSError('batch owns lock')):
            with self.assertRaisesRegex(OSError,'batch owns lock'):
                repair_from_cache(root,apply=True)
        self.assertEqual(path.read_text(encoding='utf8'),'unchanged invalid JSON')
        self.assertFalse((root/'data/annual_financials').exists())

if __name__=="__main__": unittest.main()
