"""Tests for plc_lookup.py — unit tests with mocked API and integration tests against live API."""

import json
import os
import subprocess
import sys
import unittest
import urllib.error
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import plc_lookup


SAMPLE_PRODUCT = {
    "name": "logging for Red Hat OpenShift",
    "package": "cluster-logging",
    "is_operator": True,
    "is_layered_product": True,
    "is_retired": False,
    "former_names": ["Red Hat OpenShift Logging"],
    "versions": [
        {
            "name": "6.5",
            "type": "Full Support",
            "openshift_compatibility": "4.19, 4.20, 4.21",
            "phases": [
                {
                    "name": "General availability",
                    "start_date": "N/A",
                    "end_date": "2026-04-01T00:00:00.000Z",
                    "start_date_format": "string",
                    "end_date_format": "date",
                },
                {
                    "name": "Full support",
                    "start_date": "2026-04-01T00:00:00.000Z",
                    "end_date": "Release of Logging 6.6 + 1 month",
                    "start_date_format": "date",
                    "end_date_format": "string",
                },
                {
                    "name": "Maintenance support",
                    "start_date": "Release of Logging 6.6 + 1 month",
                    "end_date": "Release of Logging 6.7",
                    "start_date_format": "string",
                    "end_date_format": "string",
                },
            ],
        },
        {
            "name": "5.9",
            "type": "End of life",
            "openshift_compatibility": "4.13, 4.14, 4.15, 4.16",
            "phases": [
                {
                    "name": "General availability",
                    "start_date": "N/A",
                    "end_date": "2024-04-04T00:00:00.000Z",
                    "start_date_format": "string",
                    "end_date_format": "date",
                },
                {
                    "name": "Full support",
                    "start_date": "2024-04-04T00:00:00.000Z",
                    "end_date": "2024-10-24T00:00:00.000Z",
                    "start_date_format": "date",
                    "end_date_format": "date",
                },
                {
                    "name": "Maintenance support",
                    "start_date": "2024-10-24T00:00:00.000Z",
                    "end_date": "2025-11-03T00:00:00.000Z",
                    "start_date_format": "date",
                    "end_date_format": "date",
                },
            ],
        },
    ],
}

SAMPLE_OCP_PRODUCT = {
    "name": "Red Hat OpenShift Container Platform",
    "package": None,
    "is_operator": False,
    "is_layered_product": False,
    "is_retired": False,
    "former_names": [],
    "versions": [
        {
            "name": "4.21",
            "type": "Full Support",
            "openshift_compatibility": None,
            "phases": [
                {
                    "name": "General availability",
                    "start_date": "N/A",
                    "end_date": "2026-02-03T00:00:00.000Z",
                    "start_date_format": "string",
                    "end_date_format": "date",
                },
            ],
        },
    ],
}

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "..", "plc_lookup.py")


# ---------------------------------------------------------------------------
# Unit tests (mocked API)
# ---------------------------------------------------------------------------


class TestApiSearchErrors(unittest.TestCase):
    @patch("plc_lookup.urllib.request.urlopen")
    def test_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        with self.assertRaises(SystemExit) as ctx:
            plc_lookup.api_search("anything")
        output = json.loads(str(ctx.exception))
        self.assertEqual(output["error"], "api_request_failed")

    @patch("plc_lookup.urllib.request.urlopen")
    def test_http_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://example.com", 500, "Internal Server Error", {}, None
        )
        with self.assertRaises(SystemExit) as ctx:
            plc_lookup.api_search("anything")
        output = json.loads(str(ctx.exception))
        self.assertEqual(output["error"], "api_request_failed")

    @patch("plc_lookup.urllib.request.urlopen")
    def test_invalid_json(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        with self.assertRaises(SystemExit) as ctx:
            plc_lookup.api_search("anything")
        output = json.loads(str(ctx.exception))
        self.assertEqual(output["error"], "invalid_response")

    @patch("plc_lookup.urllib.request.urlopen")
    def test_missing_data_key(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"unexpected": "schema"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        with self.assertRaises(SystemExit) as ctx:
            plc_lookup.api_search("anything")
        output = json.loads(str(ctx.exception))
        self.assertEqual(output["error"], "unexpected_response")


class TestNormalizeStatus(unittest.TestCase):
    def test_known_statuses(self):
        self.assertEqual(plc_lookup.normalize_status("Full Support"), "supported")
        self.assertEqual(plc_lookup.normalize_status("Maintenance Support"), "maintenance")
        self.assertEqual(plc_lookup.normalize_status("Extended Support"), "extended")
        self.assertEqual(plc_lookup.normalize_status("End of Maintenance"), "end-of-maintenance")
        self.assertEqual(plc_lookup.normalize_status("End of life"), "eol")

    def test_unknown_status(self):
        self.assertEqual(plc_lookup.normalize_status("Something New"), "unknown")
        self.assertEqual(plc_lookup.normalize_status(""), "unknown")


class TestParseOcpVersions(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(plc_lookup.parse_ocp_versions("4.19, 4.20, 4.21"), ["4.19", "4.20", "4.21"])

    def test_none(self):
        self.assertEqual(plc_lookup.parse_ocp_versions(None), [])

    def test_empty(self):
        self.assertEqual(plc_lookup.parse_ocp_versions(""), [])

    def test_single(self):
        self.assertEqual(plc_lookup.parse_ocp_versions("4.21"), ["4.21"])


class TestExtractPhaseDate(unittest.TestCase):
    def test_found(self):
        version = SAMPLE_PRODUCT["versions"][0]
        result = plc_lookup.extract_phase_date(version, "General availability")
        self.assertEqual(result["date"], "2026-04-01T00:00:00.000Z")
        self.assertEqual(result["format"], "date")

    def test_string_format(self):
        version = SAMPLE_PRODUCT["versions"][0]
        result = plc_lookup.extract_phase_date(version, "Full support")
        self.assertEqual(result["date"], "Release of Logging 6.6 + 1 month")
        self.assertEqual(result["format"], "string")

    def test_not_found(self):
        version = SAMPLE_PRODUCT["versions"][0]
        result = plc_lookup.extract_phase_date(version, "Nonexistent phase")
        self.assertIsNone(result)

    def test_case_insensitive(self):
        version = SAMPLE_PRODUCT["versions"][0]
        result = plc_lookup.extract_phase_date(version, "general availability")
        self.assertIsNotNone(result)

    def test_empty_phases(self):
        result = plc_lookup.extract_phase_date({"phases": []}, "Full support")
        self.assertIsNone(result)


class TestFormatProductVersion(unittest.TestCase):
    def test_without_target(self):
        result = plc_lookup.format_product_version(SAMPLE_PRODUCT, SAMPLE_PRODUCT["versions"][0])
        self.assertEqual(result["product"], "logging for Red Hat OpenShift")
        self.assertEqual(result["package"], "cluster-logging")
        self.assertEqual(result["version"], "6.5")
        self.assertEqual(result["status"], "supported")
        self.assertEqual(result["ocp_versions"], ["4.19", "4.20", "4.21"])
        self.assertNotIn("ocp_target", result)
        self.assertNotIn("ocp_compatible", result)

    def test_with_compatible_target(self):
        result = plc_lookup.format_product_version(SAMPLE_PRODUCT, SAMPLE_PRODUCT["versions"][0], target_ocp="4.21")
        self.assertEqual(result["ocp_target"], "4.21")
        self.assertTrue(result["ocp_compatible"])

    def test_with_incompatible_target(self):
        result = plc_lookup.format_product_version(SAMPLE_PRODUCT, SAMPLE_PRODUCT["versions"][0], target_ocp="4.16")
        self.assertFalse(result["ocp_compatible"])

    def test_ocp_product_no_compatibility(self):
        result = plc_lookup.format_product_version(SAMPLE_OCP_PRODUCT, SAMPLE_OCP_PRODUCT["versions"][0], target_ocp="4.21")
        self.assertIsNone(result["ocp_compatible"])

    def test_eol_version(self):
        result = plc_lookup.format_product_version(SAMPLE_PRODUCT, SAMPLE_PRODUCT["versions"][1])
        self.assertEqual(result["status"], "eol")


class TestPaginate(unittest.TestCase):
    def test_no_limit(self):
        items = list(range(10))
        page, meta = plc_lookup.paginate(items, limit=0, offset=0)
        self.assertEqual(page, items)
        self.assertEqual(meta["total"], 10)
        self.assertEqual(meta["returned"], 10)
        self.assertNotIn("next_offset", meta)

    def test_limit(self):
        items = list(range(10))
        page, meta = plc_lookup.paginate(items, limit=3, offset=0)
        self.assertEqual(page, [0, 1, 2])
        self.assertEqual(meta["total"], 10)
        self.assertEqual(meta["returned"], 3)
        self.assertEqual(meta["next_offset"], 3)

    def test_offset(self):
        items = list(range(10))
        page, meta = plc_lookup.paginate(items, limit=3, offset=3)
        self.assertEqual(page, [3, 4, 5])
        self.assertEqual(meta["next_offset"], 6)

    def test_last_page(self):
        items = list(range(10))
        page, meta = plc_lookup.paginate(items, limit=3, offset=9)
        self.assertEqual(page, [9])
        self.assertEqual(meta["returned"], 1)
        self.assertNotIn("next_offset", meta)

    def test_offset_beyond_total(self):
        items = list(range(5))
        page, meta = plc_lookup.paginate(items, limit=3, offset=10)
        self.assertEqual(page, [])
        self.assertEqual(meta["returned"], 0)

    def test_exact_boundary(self):
        items = list(range(6))
        page, meta = plc_lookup.paginate(items, limit=3, offset=3)
        self.assertEqual(page, [3, 4, 5])
        self.assertEqual(meta["returned"], 3)
        self.assertNotIn("next_offset", meta)


class TestCmdProducts(unittest.TestCase):
    @patch("plc_lookup.api_search")
    def test_found(self, mock_search):
        mock_search.return_value = [SAMPLE_PRODUCT]
        args = MagicMock()
        args.name = "logging"
        args.ocp = None
        args.limit = 0
        args.offset = 0
        from io import StringIO
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            ret = plc_lookup.cmd_products(args)
        output = json.loads(mock_out.getvalue())
        self.assertEqual(ret, 0)
        self.assertEqual(output["total"], 2)
        self.assertEqual(output["returned"], 2)
        self.assertEqual(output["results"][0]["version"], "6.5")
        self.assertNotIn("ocp_target", output)

    @patch("plc_lookup.api_search")
    def test_not_found(self, mock_search):
        mock_search.return_value = []
        args = MagicMock()
        args.name = "nonexistent"
        args.ocp = None
        args.limit = 0
        args.offset = 0
        from io import StringIO
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            ret = plc_lookup.cmd_products(args)
        output = json.loads(mock_out.getvalue())
        self.assertEqual(ret, 1)
        self.assertIn("error", output)

    @patch("plc_lookup.api_search")
    def test_with_ocp_flag(self, mock_search):
        mock_search.return_value = [SAMPLE_PRODUCT]
        args = MagicMock()
        args.name = "logging"
        args.ocp = "4.21"
        args.limit = 0
        args.offset = 0
        from io import StringIO
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            ret = plc_lookup.cmd_products(args)
        output = json.loads(mock_out.getvalue())
        self.assertEqual(ret, 0)
        self.assertEqual(output["ocp_target"], "4.21")
        compatible = [r for r in output["results"] if r["ocp_compatible"]]
        incompatible = [r for r in output["results"] if r["ocp_compatible"] is False]
        self.assertGreater(len(compatible), 0)
        self.assertGreater(len(incompatible), 0)

    @patch("plc_lookup.api_search")
    def test_with_pagination(self, mock_search):
        mock_search.return_value = [SAMPLE_PRODUCT]
        args = MagicMock()
        args.name = "logging"
        args.ocp = None
        args.limit = 1
        args.offset = 0
        from io import StringIO
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            ret = plc_lookup.cmd_products(args)
        output = json.loads(mock_out.getvalue())
        self.assertEqual(ret, 0)
        self.assertEqual(output["total"], 2)
        self.assertEqual(output["returned"], 1)
        self.assertEqual(output["next_offset"], 1)
        self.assertEqual(output["results"][0]["version"], "6.5")

    @patch("plc_lookup.api_search")
    def test_with_pagination_second_page(self, mock_search):
        mock_search.return_value = [SAMPLE_PRODUCT]
        args = MagicMock()
        args.name = "logging"
        args.ocp = None
        args.limit = 1
        args.offset = 1
        from io import StringIO
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            ret = plc_lookup.cmd_products(args)
        output = json.loads(mock_out.getvalue())
        self.assertEqual(ret, 0)
        self.assertEqual(output["total"], 2)
        self.assertEqual(output["returned"], 1)
        self.assertNotIn("next_offset", output)
        self.assertEqual(output["results"][0]["version"], "5.9")


class TestCmdOlmCheck(unittest.TestCase):
    @patch("plc_lookup.api_search")
    def test_found_in_batch(self, mock_search):
        mock_search.return_value = [SAMPLE_PRODUCT, SAMPLE_OCP_PRODUCT]
        args = MagicMock()
        args.ocp = "4.21"
        args.operators = '[{"package":"cluster-logging"}]'
        from io import StringIO
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            ret = plc_lookup.cmd_olm_check(args)
        output = json.loads(mock_out.getvalue())
        self.assertEqual(ret, 0)
        self.assertEqual(output["operators_checked"], 1)
        self.assertEqual(output["lifecycle_unavailable"], [])
        self.assertGreater(len(output["results"]), 0)

    @patch("plc_lookup.api_search")
    def test_not_found(self, mock_search):
        mock_search.return_value = []
        args = MagicMock()
        args.ocp = "4.21"
        args.operators = '[{"package":"no-such-operator"}]'
        from io import StringIO
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            ret = plc_lookup.cmd_olm_check(args)
        output = json.loads(mock_out.getvalue())
        self.assertEqual(ret, 0)
        self.assertEqual(output["lifecycle_unavailable"], ["no-such-operator"])
        self.assertEqual(output["results"][0]["status"], "unavailable")


# ---------------------------------------------------------------------------
# Integration tests (live API — skipped in CI if no network)
# ---------------------------------------------------------------------------


@unittest.skipUnless(
    os.environ.get("PLC_INTEGRATION_TESTS", "1") == "1",
    "Set PLC_INTEGRATION_TESTS=1 to run live API tests",
)
class TestLiveAPI(unittest.TestCase):
    """Tests against the real Red Hat Product Life Cycle API."""

    def _run_cli(self, *args):
        result = subprocess.run(
            [sys.executable, SCRIPT_PATH, *args],
            capture_output=True, text=True, timeout=30,
        )
        return result

    def test_products_logging(self):
        r = self._run_cli("products", "logging for Red Hat OpenShift")
        self.assertEqual(r.returncode, 0, r.stderr)
        output = json.loads(r.stdout)
        self.assertGreater(output["total"], 0)
        self.assertEqual(output["results"][0]["package"], "cluster-logging")
        self.assertNotIn("ocp_target", output)

    def test_products_ocp(self):
        r = self._run_cli("products", "OpenShift Container Platform")
        self.assertEqual(r.returncode, 0, r.stderr)
        output = json.loads(r.stdout)
        names = {entry["product"] for entry in output["results"]}
        self.assertTrue(any("OpenShift" in n for n in names))

    def test_products_not_found(self):
        r = self._run_cli("products", "xyzzy_nonexistent_product_12345")
        self.assertEqual(r.returncode, 1)
        output = json.loads(r.stdout)
        self.assertIn("error", output)

    def test_products_with_ocp_compatible(self):
        r = self._run_cli("products", "logging for Red Hat OpenShift", "--ocp", "4.21")
        self.assertEqual(r.returncode, 0, r.stderr)
        output = json.loads(r.stdout)
        self.assertEqual(output["ocp_target"], "4.21")
        compatible = [e for e in output["results"] if e.get("ocp_compatible")]
        self.assertGreater(len(compatible), 0, "Expected at least one compatible version")

    def test_products_pagination(self):
        r = self._run_cli("products", "logging for Red Hat OpenShift", "--limit", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        output = json.loads(r.stdout)
        self.assertEqual(output["returned"], 3)
        self.assertGreater(output["total"], 3)
        self.assertEqual(output["next_offset"], 3)

    def test_products_pagination_second_page(self):
        r = self._run_cli("products", "logging for Red Hat OpenShift", "--limit", "3", "--offset", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        output = json.loads(r.stdout)
        self.assertEqual(output["offset"], 3)
        self.assertLessEqual(output["returned"], 3)

    def test_products_with_ocp_incompatible(self):
        r = self._run_cli("products", "logging for Red Hat OpenShift", "--ocp", "3.11")
        self.assertEqual(r.returncode, 0, r.stderr)
        output = json.loads(r.stdout)
        compatible = [e for e in output["results"] if e.get("ocp_compatible")]
        self.assertEqual(len(compatible), 0, "No logging version should be compatible with OCP 3.11")

    def test_olm_check_known_operator(self):
        r = self._run_cli("olm-check", "--ocp", "4.21", "--operators", '[{"package":"cluster-logging"}]')
        self.assertEqual(r.returncode, 0, r.stderr)
        output = json.loads(r.stdout)
        self.assertEqual(output["operators_checked"], 1)
        self.assertEqual(output["lifecycle_unavailable"], [])
        self.assertGreater(len(output["results"]), 0)

    def test_olm_check_unknown_operator(self):
        r = self._run_cli("olm-check", "--ocp", "4.21", "--operators", '[{"package":"no-such-operator-xyz"}]')
        self.assertEqual(r.returncode, 0, r.stderr)
        output = json.loads(r.stdout)
        self.assertIn("no-such-operator-xyz", output["lifecycle_unavailable"])

    def test_olm_check_mixed(self):
        operators = json.dumps([
            {"package": "cluster-logging"},
            {"package": "no-such-operator-xyz"},
        ])
        r = self._run_cli("olm-check", "--ocp", "4.21", "--operators", operators)
        self.assertEqual(r.returncode, 0, r.stderr)
        output = json.loads(r.stdout)
        self.assertEqual(output["operators_checked"], 2)
        self.assertIn("no-such-operator-xyz", output["lifecycle_unavailable"])
        found = [e for e in output["results"] if e.get("package") == "cluster-logging"]
        self.assertGreater(len(found), 0)

    def test_status_values_are_normalized(self):
        r = self._run_cli("products", "logging for Red Hat OpenShift")
        self.assertEqual(r.returncode, 0, r.stderr)
        output = json.loads(r.stdout)
        valid_statuses = {"supported", "maintenance", "extended", "end-of-maintenance", "eol", "unknown"}
        for entry in output["results"]:
            self.assertIn(entry["status"], valid_statuses, f"Unexpected status: {entry['status']}")

    def test_help_flag(self):
        r = self._run_cli("-h")
        self.assertEqual(r.returncode, 0)
        self.assertIn("products", r.stdout)
        self.assertIn("olm-check", r.stdout)

    def test_subcommand_help(self):
        for cmd in ["products", "olm-check"]:
            r = self._run_cli(cmd, "-h")
            self.assertEqual(r.returncode, 0, f"{cmd} -h failed")


if __name__ == "__main__":
    unittest.main()
