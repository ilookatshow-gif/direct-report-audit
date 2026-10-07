import contextlib
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from direct_report_audit import AuditError, audit, main, number, onboard, parse_report

ROOT = Path(__file__).resolve().parents[1]
HEADER = "Placement,Impressions,Clicks,Cost,Conversions\n"


class AuditTests(unittest.TestCase):
    def test_bom_tsv_russian_decimal_and_nbsp(self):
        text = "\ufeffPlacement\tImpressions\tClicks\tCost\tConversions\nsite\t1\u00a0234\t20\t1\u202f200,50\t0,5\n"
        result = audit(text)
        self.assertEqual(result["input"]["delimiter"], "tab")
        self.assertEqual(result["totals"]["impressions"], 1234)
        self.assertEqual(result["totals"]["cost"], "1200.5")
        self.assertEqual(result["totals"]["cpa"], "2401.00")

    def test_semicolon_duplicate_aggregation(self):
        text = "Placement;Impressions;Clicks;Cost;Conversions\nsite;100;5;10,10;1\n site ;200;10;20,20;0,5\n"
        result = audit(text)
        self.assertEqual(result["input"]["placements"], 1)
        self.assertEqual(result["input"]["rows"], 2)
        self.assertEqual(result["placements"][0]["source_rows"], 2)
        self.assertEqual(result["totals"]["cost"], "30.3")
        self.assertEqual(result["totals"]["conversions"], "1.5")
        self.assertEqual(result["totals"]["cpc"], "2.02")

    def test_comma_csv_quoted_decimal_and_placement(self):
        result = audit(HEADER + '"site, with comma",100,20,"1 200,50","0,5"\n')
        self.assertEqual(result["placements"][0]["placement"], "site, with comma")
        self.assertEqual(result["totals"]["cost"], "1200.5")

    def test_csv_line_endings_lf_crlf_and_cr(self):
        for ending in ("\n", "\r\n", "\r"):
            result = audit((HEADER + "site,100,20,1000,1\n").replace("\n", ending))
            self.assertEqual(result["totals"]["cost"], "1000")

    def test_weighted_totals_not_average_of_ratios(self):
        result = audit(HEADER + "a,100,1,10,1\nb,1000,9,90,2\n")
        self.assertEqual(result["totals"]["cpc"], "10.00")
        self.assertEqual(result["totals"]["cpa"], "33.33")

    def test_zero_denominators_are_null(self):
        result = audit(HEADER + "site,10,0,0,0\n")
        self.assertIsNone(result["totals"]["cpc"])
        self.assertIsNone(result["totals"]["cpa"])
        self.assertEqual(result["candidate_count"], 0)

    def test_candidates_after_aggregation_and_explicit_thresholds(self):
        result = audit(HEADER + "a,100,10,600,0\na,100,10,600,0\nb,100,20,1200,2\nc,100,1,5000,0\n",
                       min_clicks=20, min_cost=Decimal("1000"), max_cpa=Decimal("500"))
        by_name = {item["placement"]: item for item in result["placements"]}
        self.assertEqual(by_name["a"]["reasons"], ["zero_conversion_spend"])
        self.assertEqual(by_name["b"]["reasons"], ["cpa_above_threshold"])
        self.assertFalse(by_name["c"]["manual_review"])

    def test_min_conversions_and_unrounded_threshold_comparison(self):
        result = audit(HEADER + "site,100,20,1000.001,2\n", max_cpa=Decimal("500"), min_cost=Decimal("0"))
        self.assertEqual(result["placements"][0]["cpa"], "500.00")
        self.assertTrue(result["placements"][0]["manual_review"])
        limited = audit(HEADER + "site,100,20,1000,0.5\n", max_cpa=Decimal("500"), min_conversions=Decimal("1"))
        self.assertEqual(limited["candidate_count"], 0)

    def test_cpa_equal_to_threshold_is_not_above_it(self):
        result = audit(HEADER + "site,100,20,1000,2\n", max_cpa=Decimal("500"))
        self.assertEqual(result["candidate_count"], 0)

    def test_header_reordered(self):
        result = audit("Cost,Conversions,Placement,Clicks,Impressions\n10,2,site,5,50\n")
        self.assertEqual(result["totals"]["cost"], "10")

    def test_invalid_headers_and_rows_fail_not_partial(self):
        cases = ["Placement,Impressions,Clicks,Cost,Cost\na,1,1,1,1\n",
                 HEADER + "a,1,1,1\n", HEADER + "a,1,1,1,1,extra\n",
                 HEADER + "a,1,1,1,1\ninvalid,1,1,bad,1\n",
                 HEADER + "\"unterminated,1,1,1,1\n"]
        for text in cases:
            with self.subTest(text=text):
                with self.assertRaises(AuditError):
                    audit(text)

    def test_delimiter_bearing_empty_records_are_not_silently_dropped(self):
        for row in (",,,,\n", ",,\n", " , , , , \n", '""\n'):
            with self.subTest(row=row):
                with self.assertRaises(AuditError):
                    audit(HEADER + "valid,100,20,1200,0\n" + row)
        valid = audit(HEADER + "valid,100,20,1200,0\n\n")
        self.assertEqual(valid["input"]["rows"], 1)

    def test_numeric_invalid_values_rejected(self):
        for value in ("NaN", "Infinity", "-1", "1e1000", "1,234.56", "1 20", "", "1234567890123456789"):
            with self.subTest(value=value):
                with self.assertRaises(AuditError):
                    number(value, "Cost")
        with self.assertRaises(AuditError):
            audit(HEADER + "site,1.5,1,10,1\n")
        with self.assertRaises(AuditError):
            audit(HEADER + "site,10,1.5,10,1\n")

    def test_total_rows_rejected(self):
        for name in ("TOTAL", "Итого", "Всего", "Итого:", "Total:", "Итого："):
            with self.assertRaises(AuditError):
                audit(HEADER + name + ",100,20,1000,0\n")

    def test_wrong_explicit_delimiter_rejected(self):
        with self.assertRaises(AuditError):
            parse_report(HEADER + "site,10,1,10,1\n", "tab")

    def test_synthetic_is_explicit_and_sample_sums_match(self):
        result = audit((ROOT / "examples/synthetic-placements.csv").read_text(encoding="utf-8"), max_cpa=Decimal("1000"))
        self.assertTrue(result["input"]["synthetic"])
        self.assertEqual(result["totals"]["cost"], "6000")
        self.assertEqual(result["totals"]["clicks"], 97)
        self.assertEqual(result["totals"]["conversions"], "5")
        self.assertEqual(result["candidate_count"], 2)

    def test_empty_file_and_header_only_rejected(self):
        for text in ("", "# SYNTHETIC\n", HEADER):
            with self.assertRaises(AuditError):
                audit(text)

    def test_negative_and_zero_threshold_validation(self):
        for values in ({"min_clicks": -1}, {"min_cost": Decimal("-1")}, {"max_cpa": Decimal("0")}, {"min_conversions": Decimal("0")}):
            with self.assertRaises(AuditError):
                audit(HEADER + "a,10,1,10,1\n", **values)

    def test_onboarding_once_and_audit_has_no_author_promo(self):
        with tempfile.TemporaryDirectory(dir=str(ROOT / "tests")) as folder:
            state = Path(folder) / "onboard.json"
            first, second = onboard(state), onboard(state)
            self.assertTrue(first["shown"])
            self.assertEqual(first["author"]["telegram"], "https://t.me/lookatsoul")
            self.assertFalse(second["shown"])
            self.assertNotIn("author", second)
        result = json.dumps(audit(HEADER + "a,10,1,10,1\n"))
        self.assertNotIn("lookatsoul", result)
        self.assertNotIn("lookatshow.ru", result)

    def test_machine_readable_argument_and_file_errors(self):
        for arguments in (("--json", "audit", "missing.csv"), ("audit", "--json", "missing.csv", "--min-clicks", "bad")):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main(arguments)
            self.assertEqual(status, 2)
            self.assertFalse(json.loads(output.getvalue())["ok"])

    def test_cli_argument_errors_do_not_echo_private_values(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(["--json", "doctor", "--unexpected", "private-value-not-to-echo"])
        self.assertEqual(status, 2)
        self.assertNotIn("private-value-not-to-echo", output.getvalue())

    def test_text_output_escapes_terminal_control_characters(self):
        with tempfile.TemporaryDirectory(dir=str(ROOT / "tests")) as folder:
            source = Path(folder) / "synthetic.csv"
            source.write_text(HEADER + '"site\x1b[2J",100,20,1000,0\n', encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main(["audit", str(source)])
            self.assertEqual(status, 0)
            self.assertNotIn("\x1b", output.getvalue())
            self.assertIn("\\u001b", output.getvalue())

    def test_currency_rejects_controls_and_multiline_labels(self):
        for currency in ("\x1b[2J", "RUB\nAD", "", "RUB EUR"):
            with self.assertRaises(AuditError):
                audit(HEADER + "site,100,20,1000,0\n", currency=currency)

    def test_cli_works_outside_package_without_auth_or_writes(self):
        completed = subprocess.run([sys.executable, str(ROOT / "direct_report_audit.py"), "--json", "audit",
                                    str(ROOT / "examples/synthetic-placements.csv"), "--max-cpa", "1000"],
                                   cwd=str(ROOT.parent), text=True, capture_output=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["totals"]["cost"], "6000")

    def test_local_installer_does_not_need_project_context(self):
        with tempfile.TemporaryDirectory(dir=str(ROOT / "tests")) as folder:
            prefix = Path(folder)
            completed = subprocess.run([sys.executable, str(ROOT / "install.py"), "--prefix", str(prefix)],
                                       cwd=str(ROOT.parent), text=True, capture_output=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            command = prefix / "bin/direct-report-audit"
            installed_text = command.read_text(encoding="utf-8")
            self.assertIn("SPDX-License-Identifier: MIT", installed_text)
            for notice_line in (ROOT / "LICENSE").read_text(encoding="utf-8").splitlines():
                if notice_line.strip():
                    self.assertIn(notice_line, installed_text)
            invocation = [str(command)] if os.name == "posix" else [sys.executable, str(command)]
            doctor = subprocess.run(invocation + ["--json", "doctor"], cwd=str(ROOT.parent),
                                    text=True, capture_output=True, check=False)
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            self.assertFalse(json.loads(doctor.stdout)["result"]["auth_required"])
            repeated = subprocess.run([sys.executable, str(ROOT / "install.py"), "--prefix", str(prefix)],
                                      text=True, capture_output=True, check=False)
            self.assertNotEqual(repeated.returncode, 0)


if __name__ == "__main__":
    unittest.main()
