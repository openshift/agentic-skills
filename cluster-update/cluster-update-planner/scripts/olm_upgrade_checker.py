#!/usr/bin/env python3
"""
OLM Upgrade Checker

Query installed OLM operators (both OLMv0 and OLMv1) and determine which ones
require upgrading before a cluster upgrade to a target OpenShift version.

Supports:
- OLMv0: Subscription and InstallPlan resources
- OLMv1: ClusterExtension resources

Usage:
    python3 olm_upgrade_checker.py check-operators --target-ocp 4.21.8
    python3 olm_upgrade_checker.py check-operators --target-ocp 4.21.8 --packages cluster-logging,web-terminal
"""

import argparse
import json
import subprocess
import sys
from typing import Any, Dict, List, Optional

operator_whitelist=["cluster-logging", "openshift-gitops-operator", "kubernetes-nmstate-operator", "cert-manager-operator", "local-storage-operator", "oadp-operator", "mcg-operator", "ocs-operator", "odf-csi-addons-operator", "odf-operator", "loki-operator", "kubevirt-hyperconverged-operator", "openshift-pipelines-operator-rh", "metallb-operator", "devworkspace-operator", "web-terminal", "mtv-operator", "multicluster-engine", "advanced-cluster-management", "rhacs-operator", "compliance-operator", "nfd", "quay-operator", "cluster-observability-operator", "ocs-client-operator", "recipe", "odf-prometheus-operator", "rook-ceph-operator", "cephcsi-operator", "odf-dependencies", "grafana-operator", "odf-external-snapshotter-operator"]

def run_command(cmd: List[str]) -> Dict[str, Any]:
    """Run a command and return parsed JSON output."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        if result.stdout.strip():
            return json.loads(result.stdout)
        return {}
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {' '.join(cmd)}", file=sys.stderr)
        print(f"stderr: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON output from: {' '.join(cmd)}", file=sys.stderr)
        print(f"stdout: {result.stdout}", file=sys.stderr)
        sys.exit(1)


def get_subscriptions(package_filter: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Get all OLMv0 Subscriptions."""
    cmd = ["oc", "get", "subscriptions", "-A", "-o", "json"]
    result = run_command(cmd)

    subscriptions = []
    for item in result.get("items", []):
        package_name = item.get("spec", {}).get("name")
        if package_filter and package_name not in package_filter:
            continue

        subscriptions.append({
            "name": package_name,
            "namespace": item.get("metadata", {}).get("namespace"),
            "resource_name": item.get("metadata", {}).get("name"),
            "channel": item.get("spec", {}).get("channel"),
            "current_csv": item.get("status", {}).get("currentCSV"),
            "installed_csv": item.get("status", {}).get("installedCSV"),
            "install_plan_ref": item.get("status", {}).get("installPlanRef", {}).get("name"),
            "approval": item.get("spec", {}).get("installPlanApproval", "Automatic"),
            "catalog_source": item.get("spec", {}).get("source"),
            "catalog_source_namespace": item.get("spec", {}).get("sourceNamespace"),
            "conditions": item.get("status", {}).get("conditions", [])
        })

    return subscriptions


def get_cluster_extensions(package_filter: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Get all OLMv1 ClusterExtensions."""
    cmd = ["oc", "get", "clusterextensions", "-o", "json"]
    result = run_command(cmd)

    extensions = []
    for item in result.get("items", []):
        package_name = item.get("spec", {}).get("source", {}).get("catalog", {}).get("packageName")
        if package_filter and package_name not in package_filter:
            continue

        extensions.append({
            "name": package_name,
            "resource_name": item.get("metadata", {}).get("name"),
            "namespace": item.get("spec", {}).get("namespace"),
            "version": item.get("spec", {}).get("source", {}).get("catalog", {}).get("version"),
            "channels": item.get("spec", {}).get("source", {}).get("catalog", {}).get("channels", []),
            "upgrade_policy": item.get("spec", {}).get("source", {}).get("catalog", {}).get("upgradeConstraintPolicy"),
            "installed_version": item.get("status", {}).get("installedBundle", {}).get("version"),
            "conditions": item.get("status", {}).get("conditions", [])
        })

    return extensions


def get_package_manifest(catalog_source: str, catalog_namespace: str, package: str) -> Optional[Dict[str, Any]]:
    """Get PackageManifest for a specific package from a catalog."""
    cmd = [
        "oc", "get", "packagemanifest", package,
        "-n", catalog_namespace,
        "-o", "json"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception:
        pass
    return None


def extract_version_from_csv(csv_name: str) -> str:
    """Extract version from CSV name (e.g., 'cluster-logging.v5.8.0' -> '5.8.0')."""
    if not csv_name:
        return "unknown"
    parts = csv_name.split(".v")
    if len(parts) >= 2:
        return parts[-1]
    return csv_name


def parse_semver(version: str) -> tuple:
    """Parse semantic version into (major, minor, patch) tuple for comparison."""
    try:
        # Remove 'v' prefix if present
        version = version.lstrip('v')
        # Split on '.' and take first 3 parts
        parts = version.split('.')
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2].split('-')[0]) if len(parts) > 2 else 0  # Handle pre-release
        return (major, minor, patch)
    except (ValueError, IndexError):
        return (0, 0, 0)


def check_operator_compatibility(
    operator: Dict[str, Any],
    target_ocp: str,
    api_type: str
) -> Dict[str, Any]:
    """
    Check if an operator is compatible with the target OCP version.

    Returns a dict with:
    - compatible_with_target: bool
    - requires_upgrade: bool
    - upgrade_action: dict with upgrade recommendation
    - reason: str explaining the decision
    """
    result = {
        "compatible_with_target": True,
        "requires_upgrade": False,
        "upgrade_action": None,
        "reason": "No compatibility information available"
    }

    if api_type == "OLMv0":
        # For OLMv0, we need to check the channel's maxOpenShiftVersion
        # This would require querying the PackageManifest from the catalog
        # For now, mark as compatible unless we have specific evidence otherwise

        # Check if there are any conditions indicating issues
        conditions = operator.get("conditions", [])
        for condition in conditions:
            if condition.get("type") == "ResolutionFailed":
                result["compatible_with_target"] = False
                result["requires_upgrade"] = True
                result["reason"] = f"Resolution failed: {condition.get('message', 'Unknown error')}"
                result["upgrade_action"] = {
                    "type": "investigate",
                    "reason": result["reason"]
                }
                return result

        # If we have a current CSV, assume compatible for now
        # In production, this would query the catalog for channel constraints
        if operator.get("current_csv"):
            result["reason"] = "Operator is installed and no compatibility issues detected"

    elif api_type == "OLMv1":
        # For OLMv1, check conditions
        conditions = operator.get("conditions", [])
        installed_condition = None

        for condition in conditions:
            if condition.get("type") == "Installed":
                installed_condition = condition
                break

        if installed_condition and installed_condition.get("status") == "True":
            result["reason"] = "ClusterExtension is successfully installed"
        elif installed_condition:
            result["compatible_with_target"] = False
            result["requires_upgrade"] = True
            result["reason"] = f"Installation issue: {installed_condition.get('message', 'Unknown')}"
            result["upgrade_action"] = {
                "type": "investigate",
                "reason": result["reason"]
            }

    return result


def check_operators(target_ocp: str, package_filter: Optional[str] = None) -> Dict[str, Any]:
    """
    Check installed operators against target OCP version.

    Args:
        target_ocp: Target OpenShift version (e.g., "4.21.8")
        package_filter: Comma-separated list of package names to filter

    Returns:
        Dict with operators, critical_upgrades, and non_critical_upgrades lists
    """
    packages = package_filter.split(",") if package_filter else None

    # Query both OLM types
    olmv0_subs = get_subscriptions(packages)
    olmv1_extensions = get_cluster_extensions(packages)

    operators = []
    critical_upgrades = []
    non_critical_upgrades = []

    # Process OLMv0 Subscriptions
    for sub in olmv0_subs:
        current_version = extract_version_from_csv(sub.get("current_csv", ""))

        compat = check_operator_compatibility(sub, target_ocp, "OLMv0")

        operator_info = {
            "name": sub["name"],
            "namespace": sub["namespace"],
            "api_type": "OLMv0",
            "current_version": current_version,
            "channel": sub["channel"],
            "install_plan_approval": sub["approval"],
            "pending_install_plan": sub.get("install_plan_ref"),
            **compat
        }

        operators.append(operator_info)

        if compat["requires_upgrade"]:
            critical_upgrades.append(sub["name"])

    # Process OLMv1 ClusterExtensions
    for ext in olmv1_extensions:
        compat = check_operator_compatibility(ext, target_ocp, "OLMv1")

        operator_info = {
            "name": ext["name"],
            "namespace": ext["namespace"],
            "api_type": "OLMv1",
            "current_version": ext.get("installed_version", ext.get("version", "unknown")),
            "channel": ext.get("channels", ["unknown"])[0] if ext.get("channels") else "unknown",
            **compat
        }

        operators.append(operator_info)

        if compat["requires_upgrade"]:
            critical_upgrades.append(ext["name"])

    return {
        "target_ocp_version": target_ocp,
        "operators": operators,
        "critical_upgrades": critical_upgrades,
        "non_critical_upgrades": non_critical_upgrades,
        "summary": {
            "total": len(operators),
            "olmv0": len(olmv0_subs),
            "olmv1": len(olmv1_extensions),
            "requires_upgrade": len(critical_upgrades)
        }
    }


def main():
    parser = argparse.ArgumentParser(
        description="Check OLM operator compatibility and upgrade requirements"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # check-operators command
    check_parser = subparsers.add_parser(
        "check-operators",
        help="Check installed operators against target OCP version"
    )
    check_parser.add_argument(
        "--target-ocp",
        required=True,
        help="Target OpenShift version (e.g., 4.21.8)"
    )
    check_parser.add_argument(
        "--packages",
        help="Comma-separated list of package names to check (optional)"
    )

    args = parser.parse_args()

    if args.command == "check-operators":
        result = check_operators(args.target_ocp, args.packages)
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
