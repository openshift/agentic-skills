#!/usr/bin/env python3
"""Read-only diagnosis of an OADP Backup or Restore, including volume paths."""

import argparse
import json
import os
import shutil
import subprocess
import sys


def get_json(*args):
    response = subprocess.run(["oc", "get", *args, "-o", "json"], capture_output=True, text=True)
    if response.returncode:
        raise RuntimeError(response.stderr.strip() or f"Cannot read {args[0]}")
    try:
        return json.loads(response.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON for {args[0]}: {exc}") from exc


def child_summary(kind, name, namespace, label):
    items = get_json(kind, "-n", namespace, "-l", f"velero.io/{label}-name={name}").get("items", [])
    return [{"name": item.get("metadata", {}).get("name"),
             "phase": item.get("status", {}).get("phase", "Unknown"),
             "message": item.get("status", {}).get("message", "")}
            for item in items]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("backup", "restore"), required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--namespace", default=os.getenv("OADP_NAMESPACE", "openshift-adp"))
    args = parser.parse_args()
    if shutil.which("oc") is None:
        print(json.dumps({"error": True, "code": "MISSING_TOOL", "message": "oc is not available on PATH"}))
        return 1
    try:
        operation = get_json(args.kind, args.name, "-n", args.namespace)
    except RuntimeError as exc:
        print(json.dumps({"error": True, "code": "READ_FAILED", "message": str(exc)}))
        return 1

    findings = []
    inspection_errors = []
    def add(category, evidence, next_step):
        findings.append({"category": category, "evidence": evidence, "next_step": next_step})

    status = operation.get("status", {})
    phase = status.get("phase", "New")
    backup = operation if args.kind == "backup" else None
    if args.kind == "restore":
        backup_name = operation.get("spec", {}).get("backupName")
        if backup_name:
            try:
                backup = get_json("backup", backup_name, "-n", args.namespace)
            except RuntimeError as exc:
                inspection_errors.append(f"Cannot inspect source Backup {backup_name}: {exc}")
    else:
        backup_name = args.name

    if phase == "FailedValidation":
        add("validation", status.get("validationErrors", []) or ["Operation failed validation"],
            "Correct the reported spec or storage error, then create a new operation")
    if status.get("failureReason"):
        add("operation_failure", status["failureReason"], "Inspect OADP CLI describe and logs for the failing resource")
    if status.get("errors", 0) or status.get("warnings", 0):
        add("operation_messages", {"errors": status.get("errors", 0), "warnings": status.get("warnings", 0)},
            "Read operation logs for the affected resources; counts alone do not identify the cause")

    children = {}
    if args.kind == "backup":
        kinds = (("podvolumebackups.velero.io", "pod_volume_backups"),
                 ("datauploads.velero.io", "data_uploads"))
    else:
        kinds = (("podvolumerestores.velero.io", "pod_volume_restores"),
                 ("datadownloads.velero.io", "data_downloads"))
    for kind, key in kinds:
        try:
            children[key] = child_summary(kind, args.name, args.namespace, args.kind)
        except RuntimeError as exc:
            children[key] = None
            inspection_errors.append(f"Cannot list {kind}: {exc}")
    for key, items in children.items():
        if items is None:
            continue
        failed = [item for item in items if item["phase"] in ("Failed", "Canceled")]
        if failed:
            category = "data_mover" if key in ("data_uploads", "data_downloads") else "filesystem_volume"
            next_step = ("Check the failed data operation message, node-agent readiness, storage location, and data mover controller"
                         if category == "data_mover" else
                         "Check the failed pod volume operation message, node-agent readiness, and pod volume access")
            add(category, failed, next_step)

    csi_snapshots = {}
    if backup:
        backup_status = backup.get("status", {})
        csi_attempted = backup_status.get("csiVolumeSnapshotsAttempted", 0)
        csi_completed = backup_status.get("csiVolumeSnapshotsCompleted", 0)
        native_attempted = backup_status.get("volumeSnapshotsAttempted", 0)
        native_completed = backup_status.get("volumeSnapshotsCompleted", 0)
        if csi_attempted > csi_completed or native_attempted > native_completed:
            next_step = ("Check Backup progress and CSI snapshot events if the count remains incomplete"
                         if args.kind == "backup" else
                         "Inspect source Backup snapshot errors and CSI driver events; these counts alone do not establish the Restore failure cause")
            add("snapshot" if args.kind == "backup" else "source_backup_snapshot",
                {"csi_attempted": csi_attempted, "csi_completed": csi_completed,
                 "native_attempted": native_attempted, "native_completed": native_completed},
                next_step)
        if csi_attempted:
            for kind, key, extra in (
                ("volumesnapshots.snapshot.storage.k8s.io", "volume_snapshots", ["-A"]),
                ("volumesnapshotcontents.snapshot.storage.k8s.io", "volume_snapshot_contents", []),
            ):
                try:
                    items = get_json(kind, *extra, "-l", f"velero.io/{args.kind}-name={args.name}").get("items", [])
                    csi_snapshots[key] = [{"name": item.get("metadata", {}).get("name"),
                                           "namespace": item.get("metadata", {}).get("namespace"),
                                           "ready_to_use": item.get("status", {}).get("readyToUse"),
                                           "error": (item.get("status", {}).get("error") or {}).get("message")}
                                          for item in items]
                    bad = [item for item in csi_snapshots[key] if item["error"]]
                    if bad:
                        add("csi_snapshot", bad,
                            "Inspect the affected snapshot, snapshot content, CSI driver, and Kubernetes events")
                except RuntimeError as exc:
                    csi_snapshots[key] = None
                    inspection_errors.append(f"Cannot inspect {kind}: {exc}")
        location = backup.get("spec", {}).get("storageLocation")
        if location:
            try:
                bsl = get_json("backupstoragelocation", location, "-n", args.namespace)
                bsl_phase = bsl.get("status", {}).get("phase", "Unknown")
                if bsl_phase != "Available":
                    add("storage_location", f"{location}: {bsl_phase}",
                        "Restore the BackupStorageLocation to Available before retrying")
            except RuntimeError as exc:
                inspection_errors.append(f"Cannot inspect BackupStorageLocation {location}: {exc}")

    try:
        velero = get_json("deployment", "velero", "-n", args.namespace)
        if velero.get("status", {}).get("availableReplicas", 0) < 1:
            add("velero", "Velero has no available replicas", "Check the Velero deployment and its pod events")
    except RuntimeError as exc:
        inspection_errors.append(f"Cannot inspect Velero deployment: {exc}")
    try:
        agent = get_json("daemonset", "node-agent", "-n", args.namespace).get("status", {})
        desired, ready = agent.get("desiredNumberScheduled", 0), agent.get("numberReady", 0)
        if desired == 0 or ready < desired:
            add("node_agent", f"node-agent ready {ready}/{desired}",
                "Check node-agent pods before retrying filesystem or data-mover volume operations")
    except RuntimeError as exc:
        inspection_errors.append(f"Cannot inspect node-agent: {exc}")

    cli = f"oc oadp -n {args.namespace} {args.kind}"
    commands = [f"{cli} describe {args.name} --details", f"{cli} logs {args.name}"]
    if not findings and phase in ("Failed", "PartiallyFailed"):
        add("unclassified", f"{args.kind} phase is {phase}, but inspected resources did not identify a cause",
            "Read the operation logs and relevant Kubernetes events before retrying")
    print(json.dumps({"kind": args.kind, "name": args.name, "namespace": args.namespace,
                      "phase": phase, "findings": findings, "volume_operations": children,
                      "csi_snapshots": csi_snapshots,
                      "inspection_errors": inspection_errors, "next_commands": commands,
                      "note": "Findings are observations and investigation steps, not a proven root cause"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
