#!/usr/bin/env python3
"""Read-only health report for an OADP installation."""

import argparse
import json
import os
import shutil
import subprocess
import sys


def get_json(*args):
    result = subprocess.run(["oc", "get", *args, "-o", "json"], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"oc get {args[0]} failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"oc get {args[0]} returned invalid JSON: {exc}") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default=os.getenv("OADP_NAMESPACE", "openshift-adp"))
    args = parser.parse_args()
    if shutil.which("oc") is None:
        print(json.dumps({"error": True, "code": "MISSING_TOOL", "message": "oc is not available on PATH"}))
        return 1
    namespace = args.namespace
    checks = []

    def add(name, status, detail):
        checks.append({"name": name, "status": status, "detail": detail})

    try:
        operators = get_json("deployment", "-n", namespace, "-l", "app.kubernetes.io/name=oadp-operator")
        items = operators.get("items", [])
        if not items:
            add("operator", "error", "No OADP Operator deployment found")
        elif any(item.get("status", {}).get("availableReplicas", 0) > 0 for item in items):
            add("operator", "ok", "OADP Operator deployment is available")
        else:
            add("operator", "error", "OADP Operator deployment has no available replicas")
    except RuntimeError as exc:
        add("operator", "error", str(exc))

    dpas = []
    try:
        dpas = get_json("dataprotectionapplication", "-n", namespace).get("items", [])
        if not dpas:
            add("dpa", "error", "No DataProtectionApplication found")
        for dpa in dpas:
            name = dpa.get("metadata", {}).get("name", "unknown")
            conditions = dpa.get("status", {}).get("conditions", [])
            reconciled = next((c for c in reversed(conditions) if c.get("type") == "Reconciled"), {})
            if reconciled.get("status") == "True":
                add("dpa", "ok", f"{name} is reconciled")
            else:
                add("dpa", "error", f"{name} is not reconciled: {reconciled.get('message') or 'no Reconciled condition'}")
    except RuntimeError as exc:
        add("dpa", "error", str(exc))

    try:
        velero = get_json("deployment", "velero", "-n", namespace)
        available = velero.get("status", {}).get("availableReplicas", 0)
        add("velero", "ok" if available > 0 else "error", f"Velero available replicas: {available}")
    except RuntimeError as exc:
        add("velero", "error", str(exc))

    fs_enabled = any(
        dpa.get("spec", {}).get("configuration", {}).get("velero", {}).get("defaultVolumesToFsBackup", False)
        or dpa.get("spec", {}).get("configuration", {}).get("velero", {}).get("defaultVolumesToFSBackup", False)
        for dpa in dpas
    )
    try:
        agent = get_json("daemonset", "node-agent", "-n", namespace)
        status = agent.get("status", {})
        desired, ready = status.get("desiredNumberScheduled", 0), status.get("numberReady", 0)
        agent_ok = desired > 0 and ready == desired
        severity = "ok" if agent_ok else "error" if fs_enabled else "warn"
        add("node_agent", severity, f"node-agent ready {ready}/{desired}")
    except RuntimeError as exc:
        add("node_agent", "error" if fs_enabled else "warn", str(exc))

    try:
        locations = get_json("backupstoragelocation", "-n", namespace).get("items", [])
        if not locations:
            add("storage_location", "error", "No BackupStorageLocation found")
        for location in locations:
            name = location.get("metadata", {}).get("name", "unknown")
            phase = location.get("status", {}).get("phase", "Unknown")
            mode = location.get("spec", {}).get("accessMode") or "ReadWrite"
            usable = phase == "Available" and mode != "ReadOnly"
            add("storage_location", "ok" if usable else "error", f"{name}: {phase}, {mode}")
    except RuntimeError as exc:
        add("storage_location", "error", str(exc))

    blockers = [check["detail"] for check in checks if check["status"] == "error"]
    warnings = [check["detail"] for check in checks if check["status"] == "warn"]
    print(json.dumps({"ready": not blockers, "namespace": namespace, "checks": checks,
                      "blockers": blockers, "warnings": warnings}))
    return 0 if not blockers else 1


if __name__ == "__main__":
    sys.exit(main())
