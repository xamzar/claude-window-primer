#!/usr/bin/env python3
"""Offline tests for claude-window-primer.

No network and no `claude` CLI required — the prime subprocess is stubbed.
Run with:  python3 -m unittest test_primer   (or just ./test_primer.py)
"""

import importlib.util
import json
import time
import unittest
from datetime import datetime, timedelta
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


def _reset_epoch(hhmm: str, tzname: str = "UTC"):
    """Nearest occurrence of HH:MM to now — mirrors parse_reset_time so the
    state we hand do_prime lines up with what the parser computes (otherwise the
    'same reset?' check would spuriously differ depending on time of day)."""
    hh, mm = map(int, hhmm.split(":"))
    z = ZoneInfo(tzname)
    now = datetime.now(z)
    base = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    target = min((base + timedelta(days=d) for d in (-1, 0, 1)),
                 key=lambda t: (abs(t - now), t < now))
    return target.timestamp()


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

    def test_future_reset_resolves_forward(self):
        # A reset ~2h ahead resolves to that upcoming time, not yesterday.
        soon = datetime.now(UTC) + timedelta(hours=2)
        ep = primer.parse_reset_time(
            f"resets {soon.strftime('%H:%M')} (UTC)", self.cfg)
        self.assertAlmostEqual(ep, soon.timestamp(), delta=90)

    def test_just_passed_reset_does_not_roll_a_day(self):
        # Regression: retrying within the reported minute (reset seconds in the
        # past) must stay on today, not jump ~24h forward. This is the bug that
        # silently broke the escalating-retry feature.
        now = datetime.now(UTC)
        ep = primer.parse_reset_time(
            f"resets {now.strftime('%H:%M')} (UTC)", self.cfg)
        self.assertLess(abs(ep - now.timestamp()), 120,
                        "reset in the current minute rolled forward a full day")


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
        # Stage 0 = +30s → minutes still 20 (21:20:30)
        self.assertEqual((np.hour, np.minute), (21, 20))
        self.assertAlmostEqual(np.second, 30, delta=1)
        self.assertEqual(state.get("retry_stage"), 0)

    def test_limit_escalates_retry_margin(self):
        """Same reset time, second hit → advance to +60s; third → +180s."""
        msg = json.dumps({
            "is_error": True, "api_error_status": 429,
            "result": "You've hit your session limit · resets 9:20pm (UTC)"})
        self._stub(_StubProc(1, msg))
        state = {"next_reset_epoch": _reset_epoch("21:20", "UTC")}
        primer.do_prime(self.cfg, state, reason="t")
        np = _utc(state["next_prime_epoch"])
        # retry_stage was 0, same reset → advance to 1 = +60s
        self.assertEqual(state["retry_stage"], 1)
        self.assertEqual((np.hour, np.minute), (21, 21))   # 21:21:00

        # Third hit on same reset → stage 2 = config margin (180s)
        self._stub(_StubProc(1, msg))
        state["retry_stage"] = 1   # simulate previous state
        state["next_reset_epoch"] = _reset_epoch("21:20", "UTC")
        primer.do_prime(self.cfg, state, reason="t")
        np = _utc(state["next_prime_epoch"])
        self.assertEqual(state["retry_stage"], 2)
        self.assertEqual((np.hour, np.minute), (21, 23))   # 21:23 = +3min

    def test_limit_new_reset_resets_stage(self):
        """Different reset time → retry_stage goes back to 0."""
        self._stub(_StubProc(1, json.dumps({
            "is_error": True, "api_error_status": 429,
            "result": "You've hit your session limit · resets 10:00am (UTC)"})))
        state = {"retry_stage": 2, "next_reset_epoch": _reset_epoch("21:20", "UTC")}
        primer.do_prime(self.cfg, state, reason="t")
        self.assertEqual(state["retry_stage"], 0)   # new reset, stage reset

    def test_escalation_works_when_retrying_within_reported_minute(self):
        """End-to-end regression: when the retry fires within the reported reset
        minute (reset now seconds in the past), the parser must keep it on today
        so the stage escalates instead of jumping ~24h and resetting to 0."""
        now = datetime.now(UTC)
        msg = json.dumps({
            "is_error": True, "api_error_status": 429,
            "result": f"You've hit your session limit · resets "
                      f"{now.strftime('%H:%M')} (UTC)"})
        self._stub(_StubProc(1, msg))
        # We already hit this reset once (stage 0) and are retrying now.
        state = {"next_reset_epoch": _reset_epoch(now.strftime('%H:%M'), "UTC"),
                 "retry_stage": 0}
        primer.do_prime(self.cfg, state, reason="t")
        self.assertEqual(state["retry_stage"], 1, "stage failed to escalate")
        hours_out = (state["next_prime_epoch"] - now.timestamp()) / 3600
        self.assertLess(hours_out, 1, "next prime jumped ~a day instead of escalating")

    def test_transient_failure_retries_soon(self):
        self._stub(_StubProc(1, "boom", "network down"))
        state = {}
        primer.do_prime(self.cfg, state, reason="t")
        self.assertFalse(state["last_prime_ok"])
        mins = (state["next_prime_epoch"] - time.time()) / 60
        self.assertTrue(9 <= mins <= 11, f"retry was {mins:.1f} min, expected ~10")


if __name__ == "__main__":
    unittest.main(verbosity=2)
