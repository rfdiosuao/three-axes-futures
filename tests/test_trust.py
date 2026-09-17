"""Hand-checked calculation and failure-path regressions; fixtures are synthetic."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

import pandas as pd
import daily_report
import monitor_gold


def history(end="2026-09-16"):
    dates = pd.bdate_range(end=end, periods=300)
    close = pd.Series(range(100, 400), dtype=float)
    return pd.DataFrame({"日期": dates, "开盘价": close, "最高价": close + 2,
                         "最低价": close - 2, "收盘价": close,
                         "动态结算价": close, "持仓量": 1000.0})


class ExistingRegressions(unittest.TestCase):
    def test_missing_positions_must_not_be_reported_as_empty(self):
        quote = {"ready": True, "latestPrice": 900, "preclose": 900,
                 "limitUp": 1000, "limitDown": 800, "high": 901, "low": 899}
        with patch.object(monitor_gold, "panda", side_effect=lambda a: quote if a[0] == "quote" else None), \
             patch.object(monitor_gold, "get_atr", return_value=None), contextlib.redirect_stdout(io.StringIO()) as out:
            monitor_gold.main()
        self.assertIn("LEVEL=ERROR", out.getvalue())
        self.assertNotIn("无持仓", out.getvalue())


class TrustCalculations(unittest.TestCase):
    def core(self):
        # Assert availability rather than allowing import errors to hide a missing implementation.
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec("report_core"), "validated report core is missing")
        import report_core
        return report_core

    def test_if_is_blocked_by_exposure_not_stop_budget(self):
        r = self.core().position_size(4389.4, 97.89, 300, 5_000_000)
        self.assertEqual((r["risk_lots"], r["exposure_lots"], r["lots"]), (1, 0, 0))
        self.assertEqual(r["binding"], "exposure")

    def test_missing_multiplier_suppresses_sizing(self):
        r = self.core().position_size(827, 77.41, None, 5_000_000)
        self.assertIsNone(r["lots"])

    def test_invalid_ohlc_and_duplicate_dates_are_rejected(self):
        core = self.core()
        d = history(); d.loc[10, "最高价"] = 1
        with self.assertRaises(ValueError): core.prepare_history(d)
        d = history(); d.loc[10, "日期"] = d.loc[9, "日期"]
        with self.assertRaises(ValueError): core.prepare_history(d)

    def test_insufficient_months_are_unknown_not_flat(self):
        self.assertEqual(self.core().signal(history().tail(100))["side"], "unknown")

    def test_signal_includes_recomputable_evidence(self):
        s = self.core().signal(history())
        self.assertEqual(s["side"], "long")
        self.assertEqual(s["daily"]["close"], 399)
        self.assertEqual(s["daily"]["ma"], 394.5)
        self.assertEqual(s["daily"]["ma_prev"], 393.5)
        self.assertTrue(s["includes_partial_periods"])

    def test_stale_symbol_excluded_and_no_fallback_return_in_ranking(self):
        core = self.core()
        fresh = history(); fresh.loc[len(fresh)-2, "动态结算价"] = float("nan")
        data = core.build_dataset({"M0": fresh, "C0": history("2026-09-15")}, {},
                                  "2026-09-16", {"M0": "豆粕", "C0": "玉米"}, {}, 5_000_000)
        self.assertEqual(len(data["rows"]), 1)
        self.assertIsNone(data["rows"][0]["chg"])
        self.assertEqual(data["issues"][0]["symbol"], "C0")

    def test_report_preserves_unknown_accounts_and_zero_hold_change(self):
        core = self.core()
        data = core.build_dataset({"M0": history()}, {}, "2026-09-16", {"M0":"豆粕"}, {}, 5_000_000)
        self.assertEqual(data["rows"][0]["quadrant"], "持仓不变")
        self.assertTrue(hasattr(daily_report, "render_report"), "shared report renderer is missing")
        md, xml, meta = daily_report.render_report(data)
        self.assertEqual(meta["positions_status"], "unknown")
        self.assertFalse(meta["independently_verified"])
        self.assertNotIn("无持仓、无挂单", md + xml)
        self.assertIsNone(meta["rows"][0]["lots"])

    def test_irrelevant_old_bar_does_not_block_current_window(self):
        core = self.core()
        d = history()
        old = d.iloc[[0]].copy(); old['日期'] = pd.Timestamp('2006-07-04'); old['最高价'] = 1
        data = core.build_dataset({'M0':pd.concat([old,d])}, {}, '2026-09-16', {'M0':'豆粕'}, {}, 5_000_000)
        self.assertEqual(len(data['rows']),1)
        self.assertEqual(data['rows'][0]['side'],'long')

    def test_atr_uses_previous_close_and_four_point_range(self):
        self.assertEqual(self.core().atr14(history()),4.0)

    def test_future_records_do_not_leak_into_historical_signal(self):
        core=self.core(); d=history(); future=d.iloc[[-1]].copy()
        future['日期']=pd.Timestamp('2026-09-17')
        for col in ('开盘价','最高价','最低价','收盘价'): future[col]=1.0
        data=core.build_dataset({'M0':pd.concat([d,future])},{},'2026-09-16',{'M0':'豆粕'},{},5_000_000)
        self.assertEqual(data['rows'][0]['last'],399)
        self.assertEqual(data['rows'][0]['side'],'long')

    def test_xml_escapes_provider_text_and_matches_report_counts(self):
        core=self.core()
        data=core.build_dataset({'M0':history()},{},'2026-09-16',{'M0':'A&B <示例>'},{},5_000_000)
        md,xml,meta=daily_report.render_report(data)
        root=ET.fromstring('<root>'+xml+'</root>')
        self.assertIn('A&B <示例>',''.join(root.itertext()))
        self.assertEqual((meta['scanned'],meta['up'],meta['long_n']),(1,1,1))
        self.assertIn('多头共振 1 个',md)

    def test_tampered_archive_stops_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp); f=path/'M0.csv'; history().to_csv(f,index=False)
            manifest={'schema_version':1,'files':[{'kind':'history','symbol':'M0','path':'M0.csv','sha256':daily_report.digest(f)}]}
            daily_report.write_json(path/'manifest.json',manifest)
            f.write_text('changed',encoding='utf-8')
            with self.assertRaises(ValueError):daily_report.read_archive(path/'manifest.json')

    def test_empty_replay_returns_failure_and_keeps_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            manifest={'schema_version':1,'files':[],'date':'2026-09-16','watch':{'M0':'豆粕'},
                      'source':'synthetic test fixture','rule_source':'fixture',
                      'collected_at':'2026-09-16T17:30:00+08:00','fetch_issues':[]}
            daily_report.write_json(path/'manifest.json',manifest)
            with contextlib.redirect_stdout(io.StringIO()):
                code=daily_report.main(['--replay',str(path/'manifest.json'),'--output-dir',str(path)])
            self.assertEqual(code,2)
            meta=json.loads((path/'reports/latest_meta.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['scanned'],0)
            self.assertFalse(meta['publish_ready'])

    def test_other_gold_contract_is_not_valued_at_au2612(self):
        responses={'account':{'equity':5_000_000},'positions':[{'symbol':'AU2702','volume':1}],
                   'quote':{'ready':True,'latestPrice':900,'preclose':900,'limitUp':1000,'limitDown':800}}
        with patch.object(monitor_gold,'panda',side_effect=lambda a:responses[a[0]]), \
             patch.object(monitor_gold,'get_atr',return_value=None), contextlib.redirect_stdout(io.StringIO()) as out:
            monitor_gold.main()
        self.assertIn('LEVEL=ERROR',out.getvalue())
        self.assertNotIn('浮动盈利',out.getvalue())


if __name__ == "__main__":
    unittest.main()
