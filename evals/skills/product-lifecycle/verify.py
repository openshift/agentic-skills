"""Custom verification for the product-lifecycle skill eval.

Loaded by the eval framework when a test case uses
``expected: { _fn: <function_name> }`` in test_cases.yaml.
Each function receives (result, eval_workspace, provider_name).

Uses plc_lookup.py to query live PLC API data, so expectations
stay correct as the API evolves.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
PLC_SCRIPT = REPO_ROOT / "cluster-update" / "product-lifecycle" / "scripts" / "plc_lookup.py"

sys.path.insert(0, str(PLC_SCRIPT.parent))
import plc_lookup  # noqa: E402

STATUS_MAP = {
    "Full Support": "supported",
    "Maintenance Support": "maintenance",
    "Extended Support": "extended",
    "End of Maintenance": "end-of-maintenance",
    "End of life": "eol",
}


def _run_plc_lookup(args: list[str]) -> dict:
    """Call plc_lookup.main() as a library and return parsed JSON."""
    buf = io.StringIO()
    plc_lookup.main(args, output=buf)
    return json.loads(buf.getvalue())


def _normalize_status(raw: str) -> str:
    """Map raw PLC API status to the normalized enum used in test schemas."""
    return STATUS_MAP.get(raw, "unknown")


def _find_version(results: list[dict], version: str) -> dict | None:
    """Find a specific version entry in plc_lookup products results."""
    return next((r for r in results if r["version"] == version), None)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _verify_operator_status(result, provider_name, package, version, check_ocp_compat=False):
    """Verify a single operator's lifecycle status via olm-check."""
    data = _run_plc_lookup(["olm-check", "--ocp", "4.21",
                            "--operators", json.dumps([{"package": package, "version": version}])])

    entry = data["results"][0]
    found = "error" not in entry
    expected_status = _normalize_status(entry["status"]) if found else "unknown"

    assert result["product_found"] == found, (
        f"{provider_name}: product_found expected {found}, got {result['product_found']}"
    )
    assert result["status"] == expected_status, (
        f"{provider_name}: status expected '{expected_status}', got '{result['status']}'"
    )
    if check_ocp_compat:
        expected_compat = entry.get("ocp_compatible", False) if found else False
        assert result["ocp_compatible"] == expected_compat, (
            f"{provider_name}: ocp_compatible expected {expected_compat}, got {result['ocp_compatible']}"
        )


def _verify_ocp_version(result, provider_name, version):
    """Verify an OCP platform version's lifecycle status via products lookup."""
    data = _run_plc_lookup(["products", "Red Hat OpenShift Container Platform"])

    entry = _find_version(data["results"], version)
    assert entry, f"{provider_name}: OCP {version} not found in PLC API"

    expected_status = _normalize_status(entry["status"])

    assert result["product_found"] is True, (
        f"{provider_name}: product_found expected True, got {result['product_found']}"
    )
    assert result["status"] == expected_status, (
        f"{provider_name}: status expected '{expected_status}', got '{result['status']}'"
    )


# ---------------------------------------------------------------------------
# Public verify functions (referenced by _fn in test_cases.yaml)
# ---------------------------------------------------------------------------

def verify_web_terminal_compat(
    result: dict[str, Any], _eval_workspace: Path, provider_name: str
) -> None:
    """Verify web-terminal OCP 4.21 compatibility against live API data."""
    target_ocp = "4.21"

    data = _run_plc_lookup(["products", "web terminal", "--ocp", target_ocp])

    has_supported_for_ocp = any(
        r["status"] == "Full Support" and r.get("ocp_compatible") is True
        for r in data["results"]
    )

    assert result["product_found"] is True, (
        f"{provider_name}: product_found expected True, got {result['product_found']}"
    )
    assert result["has_supported_version_for_421"] == has_supported_for_ocp, (
        f"{provider_name}: has_supported_version_for_421 expected {has_supported_for_ocp}, "
        f"got {result['has_supported_version_for_421']}"
    )


def verify_cluster_logging_status(
    result: dict[str, Any], _eval_workspace: Path, provider_name: str
) -> None:
    """Verify cluster-logging v6.5 lifecycle status and OCP 4.21 compat."""
    _verify_operator_status(result, provider_name, "cluster-logging", "6.5.1", check_ocp_compat=True)


def verify_compliance_operator_status(
    result: dict[str, Any], _eval_workspace: Path, provider_name: str
) -> None:
    """Verify compliance-operator v1.9 lifecycle status."""
    _verify_operator_status(result, provider_name, "compliance-operator", "1.9.0")


def verify_ocp_platform_status(
    result: dict[str, Any], _eval_workspace: Path, provider_name: str
) -> None:
    """Verify OCP 4.21 lifecycle status."""
    _verify_ocp_version(result, provider_name, "4.21")


def verify_ocp_old_version_status(
    result: dict[str, Any], _eval_workspace: Path, provider_name: str
) -> None:
    """Verify OCP 4.14 lifecycle status."""
    _verify_ocp_version(result, provider_name, "4.14")


_TEST1_OPERATORS = [
    {"package": "compliance-operator", "version": "1.9.0"},
    {"package": "cluster-logging", "version": "6.3.1"},
    {"package": "devworkspace-operator", "version": "0.41.0"},
    {"package": "openshift-pipelines-operator-rh", "version": "1.22.0"},
    {"package": "web-terminal", "version": "1.16.0"},
]


def verify_olm_batch_check(
    result: dict[str, Any], _eval_workspace: Path, provider_name: str
) -> None:
    """Verify batch OLM operator counts against live API data."""
    data = _run_plc_lookup([
        "olm-check", "--ocp", "4.21",
        "--operators", json.dumps(_TEST1_OPERATORS),
    ])

    api_tracked = 0
    version_tracked = 0
    ocp_compatible = 0

    for entry in data["results"]:
        if "error" in entry:
            if "not found" not in entry["error"]:
                api_tracked += 1
            continue
        api_tracked += 1
        version_tracked += 1
        if entry.get("ocp_compatible") is True:
            ocp_compatible += 1

    assert result["olm_check_ran"] is True, (
        f"{provider_name}: olm_check_ran expected True, got {result['olm_check_ran']}"
    )
    assert result["operators_checked"] == len(_TEST1_OPERATORS), (
        f"{provider_name}: operators_checked expected {len(_TEST1_OPERATORS)}, "
        f"got {result['operators_checked']}"
    )
    assert result["operators_api_tracked_count"] == api_tracked, (
        f"{provider_name}: operators_api_tracked_count expected {api_tracked}, "
        f"got {result['operators_api_tracked_count']}"
    )
    assert result["operators_version_tracked_count"] == version_tracked, (
        f"{provider_name}: operators_version_tracked_count expected {version_tracked}, "
        f"got {result['operators_version_tracked_count']}"
    )
    assert result["operators_ocp_compatible_count"] == ocp_compatible, (
        f"{provider_name}: operators_ocp_compatible_count expected {ocp_compatible}, "
        f"got {result['operators_ocp_compatible_count']}"
    )
