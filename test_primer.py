#!/usr/bin/env python3
"""Offline tests for claude-window-primer.

No network and no `claude` CLI required — the prime subprocess is stubbed.
Run with:  python3 -m unittest test_primer   (or just ./test_primer.py)
"""

import importlib.util
import json
import time
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DIR = Path(__file__).resolve().parent

# Import the script by path (it's primer.py, not an installed package).
_spec = importlib.util.spec_from_file_location("primer", DIR / "primer.py")
primer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(primer)

UTC = ZoneInfo("UTC")


def _utc(epoch):
    return datetime.fromtimestamp(epoch, UTC)


class ParseResetTime(unittest.TestCase):
    def setUp(self):
        self.cfg = dict(primer.DEFAULT_CONFIG, tz="Asia/Taipei")

    def test_real_429_message(self):
        ep = primer.parse_reset_time(
            "You've hit your session limit · resets 9:20pm (UTC)", self.cfg)
        self.assertEqual((_utc(ep).hour, _utc(ep).minute), (21, 20))

    def test_midnight_and_noon(self):
        for msg, hour in [("resets 12am (UTC)", 0), ("resets 12pm (UTC)", 12)]:
            ep = primer.parse_reset_time(msg, self.cfg)
            self.assertEqual(_utc(ep).hour, hour, msg)

    def test_named_timezone_conversion(self):
        # 7:05 PM America/New_York (EDT, -4) == 23:05 UTC
        ep = primer.parse_reset_time(
            "limit resets 7:05 PM (America/New_York)", self.cfg)
        self.assertEqual((_utc(ep).hour, _utc(ep).minute), (23, 5))

    def test_unparseable_returns_none(self):
        self.assertIsNone(primer.parse_reset_time("no hint here", self.cfg))
        self.assertIsNone(primer.parse_reset_time("", self.cfg))

    def test_always_in_the_future(self):
        ep = primer.parse_reset_time("resets 3am", self.cfg)
        self.assertGreater(ep, time.time())


class _StubProc:
    def __init__(self, returncode, stdout, stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class DoPrimeBranches(unittest.TestCase):
    """do_prime should re-anchor on a limit hit and retry fast on transient fails."""

    def setUp(self):
        self.cfg = dict(primer.DEFAULT_CONFIG, tz="UTC",
                        margin_minutes=3, retry_minutes=10)
        # Isolate side effects (state/log writes) to a throwaway dir.
        self._orig = (primer.subprocess.run, primer.STATE_PATH, primer.LOG_PATH)
        tmp = DIR / ".test-scratch"
        tmp.mkdir(exist_ok=True)
        primer.STATE_PATH = tmp / "state.json"
        primer.LOG_PATH = tmp / "primer.log"

    def tearDown(self):
        primer.subprocess.run, primer.STATE_PATH, primer.LOG_PATH = self._orig
        for f in (DIR / ".test-scratch").glob("*"):
            f.unlink()
        (DIR / ".test-scratch").rmdir()

    def _stub(self, proc):
        primer.subprocess.run = lambda cmd, **kw: proc

    def test_success_chains_one_cycle(self):
        self._stub(_StubProc(0, json.dumps({"is_error": False, "result": "pong"})))
        state = {}
        primer.do_prime(self.cfg, state, reason="t")
        self.assertTrue(state["last_prime_ok"])
        gap = state["next_reset_epoch"] - state["last_prime_epoch"]
        self.assertAlmostEqual(gap, self.cfg["cycle_minutes"] * 60, delta=2)

    def test_limit_hit_reanchors_to_reported_reset(self):
        self._stub(_StubProc(1, json.dumps({
            "is_error": True, "api_error_status": 429,
            "result": "You've hit your session limit · resets 9:20pm (UTC)"})))
        state = {}
        primer.do_prime(self.cfg, state, reason="t")
        self.assertFalse(state["last_prime_ok"])
        nr = _utc(state["next_reset_epoch"])
        np = _utc(state["next_prime_epoch"])
        self.assertEqual((nr.hour, nr.minute), (21, 20))   # the reported reset
        self.assertEqual((np.hour, np.minute), (21, 23))   # reset + margin

    def test_transient_failure_retries_soon(self):
        self._stub(_StubProc(1, "boom", "network down"))
        state = {}
        primer.do_prime(self.cfg, state, reason="t")
        self.assertFalse(state["last_prime_ok"])
        mins = (state["next_prime_epoch"] - time.time()) / 60
        self.assertTrue(9 <= mins <= 11, f"retry was {mins:.1f} min, expected ~10")


if __name__ == "__main__":
    unittest.main(verbosity=2)
