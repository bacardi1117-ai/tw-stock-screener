import contextlib
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from history_batch import annual_rows, dividend_rows, annual_metrics, run_history_batch, merge_history
from strategy_engine import evaluate_all, load_config

INCOME = [dict(date=f"{y}-{d}", type="EPS", value=2) for y in (2023,2024,2025) for d in ("03-31","06-30","09-30","12-31")]
FLOWS = [dict(date=f"{y}-12-31", type="CashFlowsFromOperatingActivities", value=100) for y in (2023,2024,2025)]
def divs(value=1):
    return [dict(year=f"{y}年", CashEarningsDistribution=value, CashStatutorySurplus=0, StockEarningsDistribution=0, StockStatutorySurplus=0) for y in range(110,115)]
class Fake:
    def __init__(self, budget, repeats=1, fail=False):
        self.budget=budget; self.errors=[]; self.stop_reason=None; self.repeats=repeats; self.fail=fail
    def close(self): pass
    def get(self, dataset, sid, start):
        for _ in range(self.repeats): self.budget.consume()
        if self.fail:
            self.errors.append(dict(category="network_error")); return None
        return INCOME if dataset.endswith("FinancialStatements") else FLOWS if dataset.endswith("CashFlowsStatement") else divs()
class HistoryTests(unittest.TestCase):
    def root(self, n=3):
        temp=tempfile.TemporaryDirectory(dir=ROOT); self.addCleanup(temp.cleanup)
        root=Path(temp.name); (root/'data/state').mkdir(parents=True)
        pd.DataFrame([dict(stock_id=str(1000+i),stock_name='Sample',eligible=i<n,market='TWSE') for i in range(n+1)]).to_csv(root/'data/state/fundamentals_universe.csv',index=False)
        return root
    def run_batch(self, root, **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            return run_history_batch(root=root,client_factory=kw.pop('factory',Fake),**kw)
    def test_progress_resume_completed_and_excluded(self):
        root=self.root(); first=self.run_batch(root,max_stocks=2)
        self.assertEqual((first['attempted'],first['completed_count'],first['remaining_count']),(2,2,1))
        second=self.run_batch(root,max_stocks=2)
        self.assertEqual((second['attempted'],second['completed_count'],second['last_run_api_calls']),(1,3,3))
        final=self.run_batch(root)
        self.assertEqual((final['attempted'],final['last_run_api_calls']),(0,0))
        self.assertNotIn('1003',final['stocks'])
    def test_360_budget_including_retries(self):
        result=self.run_batch(self.root(100),factory=lambda b:Fake(b,4))
        self.assertEqual(result['last_run_api_calls'],360)
        self.assertLessEqual(result['attempted'],100)
    def test_100_stock_ceiling(self):
        result=self.run_batch(self.root(101))
        self.assertEqual((result['attempted'],result['completed'],result['last_run_api_calls']),(100,100,300))
    def test_limits(self):
        for kwargs in [dict(api_budget=361),dict(max_stocks=101)]:
            with self.assertRaises(ValueError): self.run_batch(self.root(),**kwargs)
    def test_network_failure_is_retryable(self):
        root=self.root(1); r=self.run_batch(root,factory=lambda b:Fake(b,fail=True))
        self.assertEqual(r['retryable_stock_ids'],['1000'])
        self.assertEqual(self.run_batch(root)['completed'],1)
    def test_formal_annual_eps_precedes_quarterly_fallback(self):
        r=annual_rows('1','S',INCOME,FLOWS,{'1:2025':dict(annual_eps=7.99,source='official annual basic')})
        self.assertEqual(r[-1]['annual_eps'],7.99)
        self.assertEqual(r[0]['annual_eps'],8)
        self.assertIn('fallback',r[0]['eps_method'])
        self.assertTrue(math.isnan(annual_rows('1','S',INCOME[:-1],FLOWS)[-1]['annual_eps']))
    def test_ocf_annual_ytd_not_single_or_q3(self):
        extra=[dict(date='2025-09-30',type='CashFlowsFromOperatingActivities',value=80)]
        r=annual_rows('1','S',INCOME,FLOWS+extra)
        self.assertEqual(r[-1]['annual_operating_cash_flow'],100)
        self.assertTrue(math.isnan(annual_rows('1','S',INCOME,extra)[-1]['annual_operating_cash_flow']))
    def test_2025_quarters_deduplicate_and_sum(self):
        records=[dict(divs()[0],year=f'114年第{q}季',CashEarningsDistribution=v) for q,v in enumerate([5,5,6,6],1)]
        annual=annual_rows('1','S',INCOME,FLOWS)
        r=dividend_rows('1','S',records+[records[-1]],annual)[-1]
        self.assertEqual(r['cash_dividend'],22)
        self.assertTrue(r['annual_complete'])
        self.assertEqual(r['payout_ratio'],275)
        self.assertFalse(dividend_rows('1','S',records[-1:],annual)[-1]['annual_complete'])
    def test_zero_missing_and_negative_eps(self):
        annual=annual_rows('1','S',INCOME,FLOWS); annual[-1]['annual_eps']=-1
        zero=dividend_rows('1','S',divs(0),annual)[-1]
        missing=dividend_rows('1','S',[],annual)[-1]
        self.assertEqual(zero['dividend_status'],'zero'); self.assertEqual(zero['cash_dividend'],0)
        self.assertTrue(math.isnan(missing['cash_dividend'])); self.assertTrue(math.isnan(zero['payout_ratio']))
    def test_strategies_and_js_parity(self):
        c=load_config(); row=dict(annual_metrics(pd.DataFrame(annual_rows('1','S',INCOME,FLOWS))),roe=20,debt_ratio=30,per=15,pbr=2,dividend_years_5=5,dividend_yield=4,payout_ratio=50,dividend_growth_3y=2,dividend_min_change_3y_pct=0,free_cash_flow_single=10)
        for updates,expect_c,expect_e in [({},'pass','pass'),({'per':30},'fail','pass'),({'eps_positive_years_3':None},'missing_data','pass'),({'dividend_years_5':None},'pass','missing_data'),({'payout_ratio':90},'pass','fail')]:
            case=dict(row,**updates); py=evaluate_all(case,c)
            self.assertEqual((py['strategy_c'],py['strategy_e']),(expect_c,expect_e))
            script="import {evaluateAll} from './docs/engine.mjs';let input='';for await(const c of process.stdin)input+=c;const [r,c]=JSON.parse(input);console.log(JSON.stringify(evaluateAll(r,c)));"
            result=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps([case,c]),text=True,capture_output=True,cwd=ROOT,check=True)
            self.assertEqual(py,json.loads(result.stdout))
    def test_incomplete_cannot_overwrite_history(self):
        root=self.root(); path=root/'data/dividends/history.csv'; annual=annual_rows('1','S',INCOME,FLOWS)
        merge_history(path,dividend_rows('1','S',divs(),annual),True)
        merge_history(path,dividend_rows('1','S',[],annual),True)
        f=pd.read_csv(path); self.assertTrue(f.annual_complete.all()); self.assertTrue((f.cash_dividend==1).all())
    def test_nullable_legacy_dividend_metadata_and_mixed_source_date(self):
        root=self.root(); path=root/'data/dividends/history.csv'
        annual=annual_rows('1000','Sample',INCOME,FLOWS)
        legacy=dict(dividend_rows('1000','Sample',divs(),annual)[-1],
                    annual_complete=None,dividend_status=None,periods=None,
                    source_date=1151016.0,source=None)
        other=dict(legacy,stock_id='1001',cash_dividend=1.2345678901234567)
        path.parent.mkdir(parents=True)
        pd.DataFrame([legacy,other]).to_csv(path,index=False,encoding='utf-8-sig')
        before=pd.read_csv(path,dtype={'stock_id':str},float_precision='round_trip')
        merge_history(path,dividend_rows('1000','Sample',[],annual),True)
        after=pd.read_csv(path,dtype={'stock_id':str},float_precision='round_trip')
        saved=after.loc[(after.stock_id=='1000') & (after.year==2025)].iloc[0]
        self.assertTrue(pd.isna(saved.annual_complete))
        self.assertEqual(saved.cash_dividend,1)
        self.assertEqual(saved.source_date,1151016.0)
        pd.testing.assert_frame_equal(before.loc[before.stock_id=='1001'].reset_index(drop=True),
                                      after.loc[after.stock_id=='1001'].reset_index(drop=True),check_dtype=False)
        missing=after.loc[(after.stock_id=='1000') & (after.year==2021)].iloc[0]
        self.assertTrue(pd.isna(missing.cash_dividend))
    def test_annual_merge_preserves_verified_eps_and_missing_amount(self):
        root=self.root(); path=root/'data/annual_financials/history.csv'
        old=annual_rows('1000','Sample',INCOME,FLOWS,
                        {'1000:2025':dict(annual_eps=7.991234567890123,source='verified annual')})
        merge_history(path,old)
        merge_history(path,annual_rows('1000','Sample',INCOME,FLOWS[:-1]))
        frame=pd.read_csv(path,float_precision='round_trip')
        row=frame.loc[frame.year==2025].iloc[0]
        self.assertEqual(row.annual_eps,old[-1]['annual_eps'])
        self.assertEqual(row.annual_operating_cash_flow,100)
        self.assertEqual(row.eps_method,'verified annual')
    def test_token_not_in_progress_or_stdout(self):
        root=self.root(1); captured=io.StringIO()
        with patch.dict('os.environ',{'FINMIND_TOKEN':'secret-marker-for-test'}), contextlib.redirect_stdout(captured):
            run_history_batch(root=root,client_factory=Fake)
        self.assertNotIn('secret-marker-for-test',captured.getvalue()+(root/'data/state/history_progress.json').read_text())
if __name__=='__main__': unittest.main()
