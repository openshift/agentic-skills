"""Custom verification for the cluster-update-advisor skill eval.

Verifies that remediation plans contain the expected oc commands via
substring matching — oc command arguments are not positional, so exact
string matching would be brittle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _all_commands(result: dict[str, Any]) -> list[str]:
    """Extract all command strings from remediationPlan.actions."""
    plan = result.get("remediationPlan", {})
    return [a["command"] for a in plan.get("actions", []) if "command" in a]


def _find_command(commands: list[str], substrings: list[str]) -> int | None:
    """Find first command index containing ALL substrings. None if not found."""
    for i, cmd in enumerate(commands):
        if all(s in cmd for s in substrings):
            return i
    return None


def verify_mixed_operators_plan(
    result: dict[str, Any], eval_workspace: Path, provider_name: str
) -> None:
    """Verify the mixed OLMv0+OLMv1 remediation plan has correct commands."""
    commands = _all_commands(result)
    assert commands, f"{provider_name}: remediationPlan.actions is empty"

    # OLMv0: a single command must contain patch + resource + operator + channel
    olmv0_idx = _find_command(commands, [
        "oc patch", "subscriptions.operators.coreos.com",
        "cluster-logging", "stable-6.5",
    ])
    assert olmv0_idx is not None, (
        f"{provider_name}: no command contains all of "
        f"['oc patch', 'subscriptions.operators.coreos.com', 'cluster-logging', 'stable-6.5']. "
        f"Commands: {commands}"
    )

    # OLMv1: a single command must contain patch + resource + operator
    olmv1_idx = _find_command(commands, [
        "oc patch", "clusterextensions.olm.operatorframework.io",
        "serverless-operator",
    ])
    assert olmv1_idx is not None, (
        f"{provider_name}: no command contains all of "
        f"['oc patch', 'clusterextensions.olm.operatorframework.io', 'serverless-operator']. "
        f"Commands: {commands}"
    )

    # Platform update: a single command must contain oc adm upgrade + target version
    platform_idx = _find_command(commands, ["oc adm upgrade", "4.21.16"])
    assert platform_idx is not None, (
        f"{provider_name}: no command contains all of "
        f"['oc adm upgrade', '4.21.16']. "
        f"Commands: {commands}"
    )

    # Ordering: operator upgrades must come before platform update
    assert olmv0_idx < platform_idx, (
        f"{provider_name}: OLMv0 subscription patch (index {olmv0_idx}) "
        f"should come before platform update (index {platform_idx})"
    )
    assert olmv1_idx < platform_idx, (
        f"{provider_name}: OLMv1 clusterextension patch (index {olmv1_idx}) "
        f"should come before platform update (index {platform_idx})"
    )
