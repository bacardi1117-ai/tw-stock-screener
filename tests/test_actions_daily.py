"""Publication from a disposable runner must retain newer financial state."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess
from unittest.mock import patch
from contextlib import nullcontext

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from actions_daily import merge_csv, merge_progress, refresh_snapshot
from history_batch import publish_history


class ActionsDailyTests(unittest.TestCase):
    @staticmethod
    def temporary_directory():
        return tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])

    def test_csv_merge_keeps_remote_row_and_adds_new_row(self):
        with self.temporary_directory() as folder:
            path = Path(folder) / "prices.csv"
            pd.DataFrame([{"date": "2026-10-16", "stock_id": "2330", "market": "TWSE",
                           "close": 100}]).to_csv(path, index=False)
            incoming = pd.DataFrame([
                {"date": "2026-10-16", "stock_id": "2330", "market": "TWSE", "close": 0},
                {"date": "2026-10-19", "stock_id": "2330", "market": "TWSE", "close": 105},
            ])
            self.assertTrue(merge_csv(path, incoming, ("date", "stock_id")))
            actual = pd.read_csv(path, dtype={"stock_id": str})
            self.assertEqual(actual.close.tolist(), [100, 105])

    def test_progress_merge_does_not_downgrade_saved(self):
        with self.temporary_directory() as folder:
            path = Path(folder) / "progress.json"
            path.write_text(json.dumps({"dates": {"2026-10-16:TWSE": {"status": "saved", "rows": 100}}}))
            incoming = {"dates": {"2026-10-16:TWSE": {"status": "retryable"},
                                  "2026-10-19:TWSE": {"status": "saved", "rows": 101}}}
            self.assertTrue(merge_progress(path, incoming))
            actual = json.loads(path.read_text())
            self.assertEqual(actual["dates"]["2026-10-16:TWSE"]["status"], "saved")
            self.assertEqual(actual["dates"]["2026-10-19:TWSE"]["rows"], 101)

    def test_snapshot_rebuild_retains_published_fundamentals(self):
        root = Path(__file__).resolve().parents[1]
        with self.temporary_directory() as folder:
            temp = Path(folder)
            for name in ("data/prices/2025.csv", "data/prices/2026.csv",
                         "data/institutional/2026.csv", "data/state/institutional_progress.json",
                         "data/state/history_progress.json", "data/state/fundamentals_progress.json",
                         "docs/data/latest.json", "config/strategies.json"):
                target = temp / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((root / name).read_bytes())
            before = json.loads((temp / "docs/data/latest.json").read_text(encoding="utf-8"))
            progress_before = {name: (temp / f"data/state/{name}_progress.json").read_bytes()
                               for name in ("history", "fundamentals", "institutional")}
            metrics = refresh_snapshot(temp)
            after = json.loads((temp / "docs/data/latest.json").read_text(encoding="utf-8"))
            eps_payload = json.loads((temp / "docs/data/eps_value.json").read_text(encoding="utf-8"))
            self.assertIn("2330", eps_payload["stocks"])
            self.assertEqual(eps_payload["dates"][-1], metrics["latest_price_date"])
            for name, original in progress_before.items():
                self.assertEqual((temp / f"data/state/{name}_progress.json").read_bytes(), original)
            self.assertEqual(len(after), len(before))
            # New daily quotes can legitimately change Strategy D membership.
            # Compare the reported count with the rebuilt snapshot, not yesterday.
            self.assertEqual(metrics["strategy_d_pass"],
                             sum(row["strategy_d"] == "pass" for row in after))
            prices = pd.concat([pd.read_csv(temp / name, dtype={"stock_id": str})
                                for name in ("data/prices/2025.csv", "data/prices/2026.csv")])
            tsmc = prices[prices.stock_id == "2330"].sort_values("date").iloc[-1]
            rebuilt = next(row for row in after if row["stock_id"] == "2330")
            self.assertEqual(rebuilt["latest_date"], tsmc["date"])
            self.assertEqual(rebuilt["close"], tsmc["close"])
            for old, new in zip(before, after):
                self.assertEqual(old["stock_id"], new["stock_id"])
                for key in ("annual_eps_2025", "annual_ocf_2025", "cash_dividend_latest",
                            "revenue_yoy", "eps_yoy", "payout_ratio"):
                    self.assertEqual(old[key], new[key])

    def test_hourly_history_publish_merges_concurrent_daily_commit(self):
        with self.temporary_directory() as folder:
            base = Path(folder)
            remote, local, daily = (base / part for part in ("remote.git", "local", "daily"))
            def run(where, *args):
                result = subprocess.run(["git", *args], cwd=where,
                                        text=True, capture_output=True)
                if result.returncode:
                    raise AssertionError(f"git {args[0]} failed: {result.stderr}")
                return result.stdout.strip()
            run(base, "init", "--bare", str(remote))
            run(base, "clone", str(remote), str(local))
            for repo in (local,):
                run(repo, "config", "user.name", "test")
                run(repo, "config", "user.email", "test@example.invalid")
            (local / "docs/data").mkdir(parents=True)
            (local / "data/state").mkdir(parents=True)
            (local / "docs/data/latest.json").write_text("base", encoding="utf-8")
            (local / "docs/data/eps_value.json").write_text("base", encoding="utf-8")
            (local / "data/state/history_progress.json").write_text("base", encoding="utf-8")
            run(local, "add", ".")
            run(local, "commit", "-m", "base")
            run(local, "branch", "-M", "main")
            run(local, "push", "-u", "origin", "main")
            run(base, "clone", "-b", "main", str(remote), str(daily))
            run(daily, "config", "user.name", "test")
            run(daily, "config", "user.email", "test@example.invalid")
            (daily / "docs/data/latest.json").write_text("daily", encoding="utf-8")
            (daily / "docs/data/eps_value.json").write_text("daily", encoding="utf-8")
            (daily / "data/prices").mkdir(parents=True)
            (daily / "data/prices/2026.csv").write_text("official prices", encoding="utf-8")
            run(daily, "add", ".")
            run(daily, "commit", "-m", "daily")
            run(daily, "push", "origin", "main")
            (local / "docs/data/latest.json").write_text("history", encoding="utf-8")
            (local / "docs/data/eps_value.json").write_text("history", encoding="utf-8")
            (local / "data/state/history_progress.json").write_text("new progress", encoding="utf-8")
            def rebuild(*_args, **_kwargs):
                (local / "docs/data/latest.json").write_text("merged snapshot", encoding="utf-8")
                (local / "docs/data/eps_value.json").write_text("merged strategy data", encoding="utf-8")
            with patch("finmind_client.ApiBudget._lock", return_value=nullcontext()), \
                 patch("calculate_factors.calculate_factors", return_value=object()), \
                 patch("calculate_factors.save_factors"), \
                 patch("build_pages.build_pages", side_effect=rebuild):
                publish_history(local)
            self.assertEqual((local / "data/prices/2026.csv").read_text(), "official prices")
            self.assertEqual((local / "data/state/history_progress.json").read_text(), "new progress")
            self.assertEqual((local / "docs/data/latest.json").read_text(), "merged snapshot")
            self.assertEqual((local / "docs/data/eps_value.json").read_text(), "merged strategy data")
            self.assertEqual(run(local, "rev-parse", "HEAD"), run(local, "rev-parse", "origin/main"))


if __name__ == "__main__":
    unittest.main()
