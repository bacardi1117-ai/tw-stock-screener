"""Authenticated FinMind requests with a persistent rolling-hour safety budget."""

import json
import logging
import os
import time
from contextlib import contextmanager

import requests

from config import (
    FINMIND_API_LIMIT,
    FINMIND_API_URL,
    FINMIND_BUDGET_PATH,
    FINMIND_MAX_ATTEMPTS,
    FINMIND_TIMEOUT,
)


LOGGER = logging.getLogger(__name__)


class BudgetReached(Exception):
    """No further FinMind requests may be started this hour."""


class ApiBudget:
    def __init__(self, path=FINMIND_BUDGET_PATH, limit=FINMIND_API_LIMIT, run_limit=None,
                 on_consume=None):
        self.path = path
        self.limit = limit
        self.run_limit = run_limit
        self.on_consume = on_consume
        self.calls_this_run = 0
        self.timestamps = self._read()

    def _read(self):
        if not self.path.exists():
            return []
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            return [float(value) for value in saved.get("timestamps", [])]
        except (OSError, ValueError, TypeError):
            # A broken budget file must never silently reset the limit.
            raise BudgetReached("FinMind API budget state is unreadable")

    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(".lock")
        with lock_path.open("a+b") as handle:
            handle.seek(0)
            if handle.read(1) != b"1":
                handle.seek(0)
                handle.write(b"1")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _prune(self):
        threshold = time.time() - 3600
        self.timestamps = [stamp for stamp in self.timestamps if stamp > threshold]

    @property
    def count(self):
        self.timestamps = self._read()
        self._prune()
        return len(self.timestamps)

    def consume(self):
        if self.run_limit is not None and self.calls_this_run >= self.run_limit:
            raise BudgetReached("FinMind per-run API budget reached")
        with self._lock():
            self.timestamps = self._read()
            self._prune()
            if len(self.timestamps) >= self.limit:
                raise BudgetReached("FinMind API budget reached")
            self.timestamps.append(time.time())
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"timestamps": self.timestamps}), encoding="utf-8")
            temporary.replace(self.path)
            self.calls_this_run += 1
        if self.on_consume is not None:
            self.on_consume()


class FinMindClient:
    def __init__(self, token: str, budget: ApiBudget | None = None, session=None):
        self.budget = budget or ApiBudget()
        self.session = session or requests.Session()
        self.errors = []
        self.stop_reason = None
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def close(self):
        self.session.close()

    def get(self, dataset: str, stock_id: str, start_date: str):
        params = {"dataset": dataset, "data_id": stock_id, "start_date": start_date}
        for attempt in range(FINMIND_MAX_ATTEMPTS):
            self.budget.consume()  # Count every actual HTTP attempt, including retries.
            try:
                response = self.session.get(FINMIND_API_URL, params=params, timeout=FINMIND_TIMEOUT)
                if response.status_code == 429:
                    self.stop_reason = "rate_limit"
                    self.errors.append({"stock_id": stock_id, "dataset": dataset, "category": "rate_limit"})
                    LOGGER.warning("FinMind rate limit reached for %s (%s)", stock_id, dataset)
                    raise BudgetReached("FinMind rate limit reached")
                if response.status_code in (402, 401, 403):
                    LOGGER.warning("FinMind request failed for %s (%s: HTTP %s)", stock_id, dataset, response.status_code)
                    self.errors.append({"stock_id": stock_id, "dataset": dataset, "category": "temporary_error"})
                    return None
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                    raise ValueError("unexpected JSON structure")
                if payload.get("status") != 200:
                    LOGGER.warning("FinMind request failed for %s (%s: API status)", stock_id, dataset)
                    self.errors.append({"stock_id": stock_id, "dataset": dataset, "category": "temporary_error"})
                    return None
                return payload["data"]
            except BudgetReached:
                raise
            except requests.Timeout as exc:
                if attempt == FINMIND_MAX_ATTEMPTS - 1:
                    LOGGER.warning("FinMind request failed for %s (%s: %s)", stock_id, dataset, type(exc).__name__)
                    self.errors.append({"stock_id": stock_id, "dataset": dataset, "category": "network_error"})
                    return None
                time.sleep(0.5 * (2 ** attempt))
            except requests.ConnectionError as exc:
                if attempt == FINMIND_MAX_ATTEMPTS - 1:
                    LOGGER.warning("FinMind request failed for %s (%s: %s)", stock_id, dataset, type(exc).__name__)
                    self.errors.append({"stock_id": stock_id, "dataset": dataset, "category": "network_error"})
                    return None
                time.sleep(0.5 * (2 ** attempt))
            except (requests.RequestException, ValueError) as exc:
                if attempt == FINMIND_MAX_ATTEMPTS - 1:
                    LOGGER.warning("FinMind request failed for %s (%s: %s)", stock_id, dataset, type(exc).__name__)
                    category = "parse_error" if isinstance(exc, ValueError) else "temporary_error"
                    self.errors.append({"stock_id": stock_id, "dataset": dataset, "category": category})
                    return None
                time.sleep(0.5 * (2 ** attempt))
        return None


def token_from_environment():
    return os.environ.get("FINMIND_TOKEN", "").strip()
