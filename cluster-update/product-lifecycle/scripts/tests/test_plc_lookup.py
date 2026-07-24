"""Tests for plc_lookup.py — unit tests with mocked API and integration tests against live API."""

import io
import json
import os
import sys
import unittest
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
            ],
        },
    ],
}

SAMPLE_PRODUCT_DUPLICATE_PKG = {
    "name": "Red Hat Service Interconnect Operator",
    "package": "skupper-operator",
    "is_operator": True,
    "is_layered_product": False,
    "is_retired": False,
    "former_names": [],
    "versions": [
        {
            "name": "1.8.x",
            "type": "Full Support",
            "openshift_compatibility": "4.16, 4.17",
            "phases": [],
        },
    ],
}

SAMPLE_PRODUCT_DUPLICATE_PKG_2 = {
    "name": "Red Hat Service Interconnect",
    "package": "skupper-operator",
    "is_operator": True,
    "is_layered_product": False,
    "is_retired": False,
    "former_names": [],
    "versions": [
        {
            "name": "1.8",
            "type": "Full Support",
            "openshift_compatibility": "4.16, 4.17",
            "phases": [],
        },
        {
            "type": "Tech Preview",
            "openshift_compatibility": "4.18",
            "phases": [],
        },
    ],
}

SAMPLE_SKUPPER_NO_COMPAT = {
    "name": "Red Hat Service Interconnect",
    "package": "skupper-operator",
    "is_operator": True,
    "is_layered_product": False,
    "is_retired": False,
    "former_names": [],
    "versions": [
        {
            "name": "2.1.x",
            "type": "Full Support",
            "openshift_compatibility": None,
            "phases": [{"name": "Full support", "start_date": "2025-01-01", "end_date": "2026-01-01"}],
        },
    ],
}

SAMPLE_SKUPPER_WITH_COMPAT = {
    "name": "Red Hat Service Interconnect Operator",
    "package": "skupper-operator",
    "is_operator": True,
    "is_layered_product": False,
    "is_retired": False,
    "former_names": [],
    "versions": [
        {
            "name": "2.1.x",
            "type": "Full Support",
            "openshift_compatibility": "4.12, 4.14, 4.16, 4.17, 4.18, 4.19, 4.20, 4.21",
            "phases": [{"name": "Full support", "start_date": "2025-01-01", "end_date": "2026-01-01"}],
        },
    ],
}


def _mock_api_search(data):
    """Return a patcher that makes api_search return the given data."""
    return patch.object(plc_lookup, "api_search", return_value=data)



def _run_main(args):
    """Run plc_lookup.main() with given args and return parsed JSON output."""
    output = io.StringIO()
    plc_lookup.main(args=args, output=output)
    return json.loads(output.getvalue())


class TestParseOcpVersions(unittest.TestCase):
    def test_comma_separated(self):
        self.assertEqual(
            plc_lookup.parse_ocp_versions("4.19, 4.20, 4.21"),
            ["4.19", "4.20", "4.21"],
        )

    def test_empty_string(self):
        self.assertEqual(plc_lookup.parse_ocp_versions(""), [])

    def test_none(self):
        self.assertEqual(plc_lookup.parse_ocp_versions(None), [])


class TestFormatProductVersion(unittest.TestCase):
    def test_basic_format(self):
        result = plc_lookup.format_product_version(
            SAMPLE_PRODUCT, SAMPLE_PRODUCT["versions"][0]
        )
        self.assertEqual(
            result["product"], "logging for Red Hat OpenShift",
            "Product name should match the source product",
        )
        self.assertEqual(result["version"], "6.5")
        self.assertEqual(
            result["status"], "Full Support",
            "Status should be the raw API type, not normalized",
        )
        self.assertEqual(result["ocp_versions"], ["4.19", "4.20", "4.21"])
        self.assertEqual(
            result["former_names"], ["Red Hat OpenShift Logging"],
            "former_names should be preserved from the product",
        )
        self.assertEqual(result["package"], "cluster-logging")

    def test_all_phases_included(self):
        result = plc_lookup.format_product_version(
            SAMPLE_PRODUCT, SAMPLE_PRODUCT["versions"][0]
        )
        self.assertEqual(
            len(result["phases"]), 3,
            f"Expected 3 phases for version 6.5, got {len(result['phases'])}",
        )
        phase_names = [p["name"] for p in result["phases"]]
        self.assertEqual(
            phase_names,
            ["General availability", "Full support", "Maintenance support"],
        )

    def test_ocp_compatible_true(self):
        result = plc_lookup.format_product_version(
            SAMPLE_PRODUCT, SAMPLE_PRODUCT["versions"][0], target_ocp="4.21"
        )
        self.assertEqual(result["ocp_target"], "4.21")
        self.assertTrue(
            result["ocp_compatible"],
            "logging 6.5 should be compatible with OCP 4.21",
        )

    def test_ocp_compatible_false(self):
        result = plc_lookup.format_product_version(
            SAMPLE_PRODUCT, SAMPLE_PRODUCT["versions"][0], target_ocp="4.16"
        )
        self.assertFalse(
            result["ocp_compatible"],
            "logging 6.5 should NOT be compatible with OCP 4.16",
        )

    def test_ocp_compatible_none_when_no_compat_data(self):
        product = {"name": "OCP", "versions": [{"name": "4.21", "type": "Full Support"}]}
        result = plc_lookup.format_product_version(
            product, product["versions"][0], target_ocp="4.21"
        )
        self.assertIsNone(
            result["ocp_compatible"],
            "ocp_compatible should be None when no openshift_compatibility data",
        )

    def test_no_ocp_fields_without_target(self):
        result = plc_lookup.format_product_version(
            SAMPLE_PRODUCT, SAMPLE_PRODUCT["versions"][0]
        )
        self.assertNotIn("ocp_target", result)
        self.assertNotIn("ocp_compatible", result)

    def test_raw_status_passthrough(self):
        """Raw API types are passed through without normalization."""
        for raw_type in ["Full Support", "Maintenance Support", "End of Maintenance",
                         "Extended Support", "End of life", ""]:
            product = {"name": "test", "versions": [{"name": "1.0", "type": raw_type}]}
            result = plc_lookup.format_product_version(product, product["versions"][0])
            self.assertEqual(
                result["status"], raw_type,
                f"Status '{raw_type}' should pass through unchanged",
            )


class TestCmdProducts(unittest.TestCase):
    def test_found(self):
        with _mock_api_search([SAMPLE_PRODUCT]):
            output = _run_main(["products", "logging for Red Hat OpenShift"])
        self.assertEqual(output["total"], 2, "Should return 2 versions (6.5, 5.9)")
        for result in output["results"]:
            self.assertEqual(
                result["product"], "logging for Red Hat OpenShift",
                "All results should be from the queried product",
            )

    def test_not_found(self):
        with _mock_api_search([]):
            output = _run_main(["products", "nonexistent"])
        self.assertEqual(output["error"], "no products found")
        self.assertEqual(output["query"], "nonexistent")

    def test_with_ocp_target(self):
        with _mock_api_search([SAMPLE_PRODUCT]):
            output = _run_main(["products", "logging", "--ocp", "4.21"])
        self.assertEqual(output["ocp_target"], "4.21")
        compatible = [r for r in output["results"] if r.get("ocp_compatible")]
        self.assertTrue(
            len(compatible) > 0,
            "At least one version should be compatible with OCP 4.21",
        )
        v65 = next(r for r in output["results"] if r["version"] == "6.5")
        self.assertTrue(v65["ocp_compatible"], "logging 6.5 should be OCP 4.21 compatible")

    def test_no_ocp_target(self):
        with _mock_api_search([SAMPLE_PRODUCT]):
            output = _run_main(["products", "logging"])
        self.assertNotIn("ocp_target", output)


class TestCmdOlmCheck(unittest.TestCase):
    def test_found_with_version(self):
        """Version provided and tracked → no error, with status."""
        with _mock_api_search([SAMPLE_PRODUCT]):
            output = _run_main([
                "olm-check", "--ocp", "4.21",
                "--operators", '[{"package":"cluster-logging","version":"6.5.0"}]',
            ])
        self.assertEqual(output["ocp_target"], "4.21")
        self.assertEqual(output["operators_checked"], 1)
        self.assertEqual(output["lifecycle_unavailable"], [])
        r = output["results"][0]
        self.assertNotIn("error", r)
        self.assertEqual(r["requested_version"], "6.5")
        self.assertEqual(r["product"], "logging for Red Hat OpenShift")
        self.assertEqual(r["status"], "Full Support")
        self.assertTrue(r["ocp_compatible"])

    def test_found_with_v_prefix(self):
        """Leading 'v' in version is stripped before matching."""
        with _mock_api_search([SAMPLE_PRODUCT]):
            output = _run_main([
                "olm-check", "--ocp", "4.21",
                "--operators", '[{"package":"cluster-logging","version":"v6.5.0"}]',
            ])
        r = output["results"][0]
        self.assertNotIn("error", r)
        self.assertEqual(r["requested_version"], "6.5")
        self.assertEqual(r["product"], "logging for Red Hat OpenShift")

    def test_found_with_x_suffix(self):
        """API version '1.8.x' matches normalized '1.8'."""
        with _mock_api_search([SAMPLE_PRODUCT_DUPLICATE_PKG]):
            output = _run_main([
                "olm-check", "--ocp", "4.17",
                "--operators", '[{"package":"skupper-operator","version":"1.8.2"}]',
            ])
        r = output["results"][0]
        self.assertNotIn("error", r)
        self.assertEqual(r["requested_version"], "1.8")
        self.assertEqual(r["product"], "Red Hat Service Interconnect Operator")

    def test_prefers_product_with_ocp_compatibility(self):
        """When multiple products share a package, prefer the one with openshift_compatibility."""
        with _mock_api_search([SAMPLE_SKUPPER_NO_COMPAT, SAMPLE_SKUPPER_WITH_COMPAT]):
            output = _run_main([
                "olm-check", "--ocp", "4.17",
                "--operators", '[{"package":"skupper-operator","version":"2.1.0"}]',
            ])
        r = output["results"][0]
        self.assertNotIn("error", r)
        self.assertEqual(r["product"], "Red Hat Service Interconnect Operator")
        self.assertTrue(r["ocp_compatible"])

    def test_prefers_product_with_ocp_compatibility_reversed_order(self):
        """Same preference regardless of product order in API response."""
        with _mock_api_search([SAMPLE_SKUPPER_WITH_COMPAT, SAMPLE_SKUPPER_NO_COMPAT]):
            output = _run_main([
                "olm-check", "--ocp", "4.17",
                "--operators", '[{"package":"skupper-operator","version":"2.1.0"}]',
            ])
        r = output["results"][0]
        self.assertNotIn("error", r)
        self.assertEqual(r["product"], "Red Hat Service Interconnect Operator")
        self.assertTrue(r["ocp_compatible"])

    def test_version_entry_missing_name(self):
        """Version entries with no 'name' key don't crash."""
        with _mock_api_search([SAMPLE_PRODUCT_DUPLICATE_PKG_2]):
            output = _run_main([
                "olm-check", "--ocp", "4.17",
                "--operators", '[{"package":"skupper-operator","version":"1.8.0"}]',
            ])
        r = output["results"][0]
        self.assertNotIn("error", r)
        self.assertEqual(r["requested_version"], "1.8")

    def test_version_entry_missing_name_no_version(self):
        """No version + nameless entries don't crash; nameless excluded from available_versions."""
        with _mock_api_search([SAMPLE_PRODUCT_DUPLICATE_PKG_2]):
            output = _run_main([
                "olm-check", "--ocp", "4.17",
                "--operators", '[{"package":"skupper-operator"}]',
            ])
        r = output["results"][0]
        self.assertNotIn("error", r)
        self.assertIn("1.8", r["available_versions"])
        self.assertNotIn(None, r["available_versions"])

    def test_found_no_version(self):
        """No version provided → no error, with available_versions."""
        with _mock_api_search([SAMPLE_PRODUCT]):
            output = _run_main([
                "olm-check", "--ocp", "4.21",
                "--operators", '[{"package":"cluster-logging"}]',
            ])
        r = output["results"][0]
        self.assertNotIn("error", r)
        self.assertIn("available_versions", r)
        self.assertIn("6.5", r["available_versions"])
        self.assertIn("5.9", r["available_versions"])

    def test_version_not_tracked(self):
        """Package exists but version doesn't → error with available_versions."""
        with _mock_api_search([SAMPLE_PRODUCT]):
            output = _run_main([
                "olm-check", "--ocp", "4.21",
                "--operators", '[{"package":"cluster-logging","version":"9.9.0"}]',
            ])
        r = output["results"][0]
        self.assertEqual(r["requested_version"], "9.9")
        self.assertIn("version 9.9 not tracked", r["error"])
        self.assertIn("6.5", r["available_versions"])
        self.assertEqual(output["lifecycle_unavailable"], ["cluster-logging"])

    def test_package_not_found(self):
        """Package not in API → error, in lifecycle_unavailable."""
        with _mock_api_search([]):
            output = _run_main([
                "olm-check", "--ocp", "4.21",
                "--operators", '[{"package":"nonexistent-operator"}]',
            ])
        self.assertEqual(output["operators_checked"], 1)
        self.assertEqual(output["lifecycle_unavailable"], ["nonexistent-operator"])
        r = output["results"][0]
        self.assertIn("not found", r["error"])

    def test_mixed_results(self):
        """Batch with success, version-missing, and package-missing operators."""
        with _mock_api_search([SAMPLE_PRODUCT]):
            output = _run_main([
                "olm-check", "--ocp", "4.21",
                "--operators", json.dumps([
                    {"package": "cluster-logging", "version": "6.5.0"},
                    {"package": "cluster-logging", "version": "9.9.0"},
                    {"package": "nonexistent", "version": "1.0.0"},
                ]),
            ])
        self.assertEqual(output["operators_checked"], 3)
        self.assertNotIn("error", output["results"][0])
        self.assertIn("not tracked", output["results"][1]["error"])
        self.assertIn("not found", output["results"][2]["error"])
        self.assertEqual(output["lifecycle_unavailable"], ["cluster-logging", "nonexistent"])

    def test_single_api_call(self):
        """olm-check fetches all products in one call."""
        call_count = [0]

        def counting_search(url=plc_lookup.API_BASE, name=None):
            call_count[0] += 1
            return [SAMPLE_PRODUCT]

        with patch.object(plc_lookup, "api_search", side_effect=counting_search):
            output = _run_main([
                "olm-check", "--ocp", "4.21",
                "--operators", '[{"package":"cluster-logging"}]',
            ])
        self.assertNotIn("error", output["results"][0])
        self.assertEqual(call_count[0], 1, "Should call api_search exactly once")

    def test_empty_package(self):
        """Empty package name → error."""
        with _mock_api_search([SAMPLE_PRODUCT]):
            output = _run_main([
                "olm-check", "--ocp", "4.21",
                "--operators", '[{"package":""},{}]',
            ])
        self.assertEqual(output["operators_checked"], 2)
        self.assertEqual(output["lifecycle_unavailable"], ["", ""])
        self.assertIn("error", output["results"][0])
        self.assertIn("error", output["results"][1])


class TestApiSearchErrors(unittest.TestCase):
    """Tests for api_search error handling at the external boundary."""

    def test_url_error_produces_json(self):
        with patch.object(plc_lookup.urllib.request, "urlopen",
                          side_effect=plc_lookup.urllib.error.URLError("connection refused")):
            with self.assertRaises(SystemExit) as ctx:
                plc_lookup.api_search(name="test")
            error = json.loads(str(ctx.exception))
            self.assertEqual(error["error"], "api_request_failed")
            self.assertIn("connection refused", error["detail"])

    def test_invalid_json_produces_error(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch.object(plc_lookup.urllib.request, "urlopen", return_value=mock_resp):
            with self.assertRaises(SystemExit) as ctx:
                plc_lookup.api_search(name="test")
            error = json.loads(str(ctx.exception))
            self.assertEqual(error["error"], "invalid_response")

    def test_missing_data_key_produces_error(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"results": []}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch.object(plc_lookup.urllib.request, "urlopen", return_value=mock_resp):
            with self.assertRaises(SystemExit) as ctx:
                plc_lookup.api_search(name="test")
            error = json.loads(str(ctx.exception))
            self.assertEqual(error["error"], "unexpected_response")
            self.assertIn("results", error["keys"])


class TestHelp(unittest.TestCase):
    def test_main_help(self):
        with self.assertRaises(SystemExit) as ctx:
            plc_lookup.main(args=["-h"], output=io.StringIO())
        self.assertEqual(ctx.exception.code, 0)

    def test_products_help(self):
        with self.assertRaises(SystemExit) as ctx:
            plc_lookup.main(args=["products", "-h"], output=io.StringIO())
        self.assertEqual(ctx.exception.code, 0)

    def test_olm_check_help(self):
        with self.assertRaises(SystemExit) as ctx:
            plc_lookup.main(args=["olm-check", "-h"], output=io.StringIO())
        self.assertEqual(ctx.exception.code, 0)


@unittest.skipUnless(
    os.environ.get("PLC_LIVE_TESTS"), "Set PLC_LIVE_TESTS=1 to run live API tests"
)
class TestLiveAPI(unittest.TestCase):
    """Integration tests against the live Red Hat Product Life Cycle API."""

    def test_ocp_product_found(self):
        output = _run_main(["products", "Red Hat OpenShift Container Platform"])
        self.assertGreater(
            output["total"], 0,
            "Red Hat OpenShift Container Platform should exist in the PLC API",
        )
        product_names = {r["product"] for r in output["results"]}
        self.assertIn(
            "Red Hat OpenShift Container Platform", product_names,
            f"Expected exact product name, got: {product_names}",
        )

    def test_logging_product_found(self):
        output = _run_main(["products", "logging for Red Hat OpenShift"])
        product_names = {r["product"] for r in output["results"]}
        self.assertIn(
            "logging for Red Hat OpenShift", product_names,
            f"Expected 'logging for Red Hat OpenShift', got: {product_names}",
        )
        packages = {r["package"] for r in output["results"]}
        self.assertIn(
            "cluster-logging", packages,
            "logging product should have package=cluster-logging",
        )

    def test_logging_ocp_421_compatible(self):
        output = _run_main([
            "products", "logging for Red Hat OpenShift", "--ocp", "4.21",
        ])
        compatible = [
            r for r in output["results"]
            if r.get("ocp_compatible") and r["product"] == "logging for Red Hat OpenShift"
        ]
        self.assertGreater(
            len(compatible), 0,
            "At least one logging version should be compatible with OCP 4.21",
        )

    def test_logging_ocp_311_not_compatible(self):
        output = _run_main([
            "products", "logging for Red Hat OpenShift", "--ocp", "3.11",
        ])
        compatible = [
            r for r in output["results"]
            if r.get("ocp_compatible") and r["product"] == "logging for Red Hat OpenShift"
        ]
        self.assertEqual(
            compatible, [],
            "No logging version should be compatible with OCP 3.11",
        )

    def test_olm_check_cluster_logging(self):
        output = _run_main([
            "olm-check", "--ocp", "4.21",
            "--operators", '[{"package":"cluster-logging"}]',
        ])
        self.assertEqual(output["operators_checked"], 1)
        self.assertEqual(
            output["lifecycle_unavailable"], [],
            "cluster-logging should have lifecycle data",
        )
        found_products = [r["product"] for r in output["results"] if "product" in r]
        self.assertIn(
            "logging for Red Hat OpenShift", found_products,
            f"cluster-logging should map to logging product, got: {found_products}",
        )

    def test_olm_check_nonexistent(self):
        output = _run_main([
            "olm-check", "--ocp", "4.21",
            "--operators", '[{"package":"does-not-exist-xyz"}]',
        ])
        self.assertEqual(output["lifecycle_unavailable"], ["does-not-exist-xyz"])

    def test_former_names_preserved(self):
        output = _run_main(["products", "Red Hat OpenShift Container Platform"])
        ocp_results = [
            r for r in output["results"]
            if r["product"] == "Red Hat OpenShift Container Platform"
        ]
        self.assertGreater(len(ocp_results), 0)
        all_former = set()
        for r in ocp_results:
            all_former.update(r.get("former_names", []))
        self.assertTrue(
            len(all_former) > 0,
            f"OCP should have former_names, got: {all_former}",
        )


if __name__ == "__main__":
    unittest.main()
