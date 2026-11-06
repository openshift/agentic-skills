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


def _assert_any_command_contains(commands: list[str], substring: str, label: str, provider: str):
    """Assert at least one command contains the substring."""
    assert any(substring in cmd for cmd in commands), (
        f"{provider}: no command contains '{substring}' ({label}). "
        f"Commands: {commands}"
    )


def verify_mixed_operators_plan(
    result: dict[str, Any], eval_workspace: Path, provider_name: str
) -> None:
    """Verify the mixed OLMv0+OLMv1 remediation plan has correct commands."""
    commands = _all_commands(result)
    assert commands, f"{provider_name}: remediationPlan.actions is empty"

    # OLMv0: subscription patch for cluster-logging
    _assert_any_command_contains(
        commands, "subscriptions.operators.coreos.com",
        "OLMv0 subscription patch", provider_name
    )
    _assert_any_command_contains(
        commands, "cluster-logging",
        "cluster-logging operator name", provider_name
    )
    _assert_any_command_contains(
        commands, "stable-6.5",
        "target channel stable-6.5", provider_name
    )

    # OLMv1: clusterextension patch for serverless
    _assert_any_command_contains(
        commands, "clusterextensions.olm.operatorframework.io",
        "OLMv1 clusterextension patch", provider_name
    )
    _assert_any_command_contains(
        commands, "serverless-operator",
        "serverless operator name", provider_name
    )

    # Platform update
    _assert_any_command_contains(
        commands, "oc adm upgrade",
        "platform update command", provider_name
    )
    _assert_any_command_contains(
        commands, "4.21.16",
        "target version in platform update", provider_name
    )
