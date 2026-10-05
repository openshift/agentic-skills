#!/usr/bin/env python3
"""Summarize a Restore and its filesystem and data-mover volume operations."""

import argparse
import collections
import json
import os
import shutil
import subprocess
import sys


def get_json(*args):
    response = subprocess.run(["oc", "get", *args, "-o", "json"], capture_output=True, text=True)
    if response.returncode:
        raise RuntimeError(response.stderr.strip() or f"Cannot read {args[0]}")
    return json.loads(response.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--namespace", default=os.getenv("OADP_NAMESPACE", "openshift-adp"))
    args = parser.parse_args()
    if shutil.which("oc") is None:
        print(json.dumps({"error": True, "code": "MISSING_TOOL", "message": "oc is not available on PATH"}))
        return 1
    try:
        restore = get_json("restore", args.name, "-n", args.namespace)
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": True, "code": "READ_FAILED", "message": str(exc)}))
        return 1
    status = restore.get("status", {})
    inspection_errors = []
    volumes = {}
    for kind, output_name in (("podvolumerestores.velero.io", "pod_volume_restores"),
                              ("datadownloads.velero.io", "data_downloads")):
        try:
            items = get_json(kind, "-n", args.namespace, "-l", f"velero.io/restore-name={args.name}").get("items", [])
            volumes[output_name] = dict(collections.Counter(item.get("status", {}).get("phase", "Unknown") for item in items))
        except (RuntimeError, json.JSONDecodeError) as exc:
            inspection_errors.append(f"Cannot inspect {kind}: {exc}")
            volumes[output_name] = None
    phase = status.get("phase", "New")
    errors = status.get("errors", 0)
    item_failures = status.get("restoreItemOperationsFailed", 0)
    unfinished_volumes = any(counts and any(p != "Completed" for p in counts) for counts in volumes.values())
    succeeded = phase == "Completed" and errors == 0 and item_failures == 0 and not unfinished_volumes
    guidance = []
    if phase in ("Failed", "PartiallyFailed", "FailedValidation") or errors or unfinished_volumes:
        guidance.append(f"Inspect with oc oadp -n {args.namespace} restore describe {args.name} --details and oc oadp -n {args.namespace} restore logs {args.name}.")
        guidance.append("Use the diagnose skill to examine CSI, node-agent, and data-mover failures.")
    if inspection_errors:
        guidance.append("Volume inspection is incomplete; do not claim volume restoration was verified.")
    if phase not in ("Completed", "PartiallyFailed", "Failed", "FailedValidation"):
        guidance.append("Restore is still in progress; run monitor_restore.py again.")
    print(json.dumps({"name": args.name, "backup_name": restore.get("spec", {}).get("backupName"),
                      "phase": phase, "succeeded": succeeded, "warnings": status.get("warnings", 0),
                      "errors": errors, "failure_reason": status.get("failureReason"),
                      "validation_errors": status.get("validationErrors", []),
                      "items_restored": (status.get("progress") or {}).get("itemsRestored", 0),
                      "total_items": (status.get("progress") or {}).get("totalItems", 0),
                      "restore_item_operations_failed": item_failures,
                      "namespace_mapping": restore.get("spec", {}).get("namespaceMapping", {}),
                      "volume_restores": volumes, "inspection_errors": inspection_errors,
                      "guidance": guidance}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
