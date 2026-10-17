import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

MOD = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'src/codex-acc'))
FETCH = MOD['fetch_account_limits']

class PlanTests(unittest.TestCase):
    def fetch(self, payload):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps(payload).encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'account.json'
            path.write_text(json.dumps({'tokens': {'access_token': 'fictional-token'}}))
            with patch.object(FETCH.__globals__['urllib'].request, 'urlopen', return_value=Response()):
                return FETCH({'file_path': str(path), 'plan': 'PLUS'})

    def test_current_plan_overrides_old_saved_plus_claim(self):
        for plan in ('free', 'plus', 'pro', 'team', 'business', 'enterprise', 'future_plan'):
            with self.subTest(plan=plan):
                result = self.fetch({'plan_type': plan, 'rate_limit': {'primary_window': {'limit_window_seconds': 18000, 'used_percent': 17}}})
                self.assertTrue(result['ok'])
                self.assertEqual(result['plan_type'], plan.upper())
                self.assertFalse(result['has_weekly_cap'])

    def test_missing_live_plan_is_not_invented_from_saved_claim(self):
        result = self.fetch({'rate_limit': {'primary_window': {'limit_window_seconds': 18000, 'used_percent': 17}}})
        self.assertEqual(result['plan_type'], '')

    def test_missing_usage_is_not_a_fully_available_account(self):
        for payload in ({}, {'rate_limit': {'primary_window': {'limit_window_seconds': 18000}}}):
            self.assertFalse(self.fetch(payload)['ok'])
