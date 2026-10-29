#!/usr/bin/env python3
"""Validate and create a namespace backup schedule through the OADP CLI."""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys


DNS_LABEL = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")


def fail(code, message):
    print(json.dumps({"error": True, "code": code, "message": message}))
    return 1


def command(*args):
    return subprocess.run(["oc", *args], capture_output=True, text=True)


def get_json(*args):
    result = command("get", *args, "-o", "json")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"Cannot read {args[0]}")
    return json.loads(result.stdout)


def valid_name(name):
    return len(name) <= 63 and DNS_LABEL.fullmatch(name) is not None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--namespaces", required=True, help="Comma-separated application namespaces")
    parser.add_argument("--schedule", required=True, help="UTC cron expression or @every duration")
    parser.add_argument("--storage-location")
    parser.add_argument("--ttl")
    method = parser.add_mutually_exclusive_group()
    method.add_argument("--fs-backup", action="store_true")
    method.add_argument("--snapshot-volumes", action="store_true")
    parser.add_argument("--run-immediately", action="store_true")
    parser.add_argument("--paused", action="store_true")
    parser.add_argument("--emit-only", action="store_true")
    parser.add_argument("--namespace", default=os.getenv("OADP_NAMESPACE", "openshift-adp"))
    args = parser.parse_args()
    if shutil.which("oc") is None:
        return fail("MISSING_TOOL", "oc is not available on PATH")

    namespaces = args.namespaces.split(",")
    if not valid_name(args.name) or not namespaces or any(not valid_name(n) for n in namespaces):
        return fail("INVALID_NAME", "Schedule and application namespaces must be DNS labels of at most 63 characters")
    if "\n" in args.schedule or "\r" in args.schedule or not args.schedule.strip():
        return fail("INVALID_SCHEDULE", "Supply one UTC cron expression or @every duration")
    if args.ttl and not re.fullmatch(r"(?:[0-9]+[hms])+", args.ttl):
        return fail("INVALID_TTL", "Use a duration such as 720h or 1h30m")
    if command("whoami").returncode:
        return fail("AUTH_FAILED", "Log in to the OpenShift cluster first")
    for namespace in namespaces:
        if command("get", "namespace", namespace, "-o", "name").returncode:
            return fail("NAMESPACE_NOT_FOUND", f"Cannot read application namespace {namespace}")

    try:
        dpas = get_json("dataprotectionapplication", "-n", args.namespace).get("items", [])
        if len(dpas) != 1:
            return fail("DPA_SELECTION", "Expected one DataProtectionApplication in the OADP namespace")
        dpa = dpas[0]
        reconciled = [c for c in dpa.get("status", {}).get("conditions", []) if c.get("type") == "Reconciled"]
        if not reconciled or reconciled[-1].get("status") != "True":
            return fail("DPA_NOT_READY", "DataProtectionApplication is not reconciled")
        if get_json("deployment", "velero", "-n", args.namespace).get("status", {}).get("availableReplicas", 0) < 1:
            return fail("VELERO_NOT_READY", "Velero deployment has no available replicas")
        locations = get_json("backupstoragelocation", "-n", args.namespace).get("items", [])
    except (RuntimeError, json.JSONDecodeError) as exc:
        return fail("PREFLIGHT_FAILED", str(exc))

    if args.storage_location:
        selected = next((b for b in locations if b.get("metadata", {}).get("name") == args.storage_location), None)
    else:
        defaults = [b for b in locations if b.get("spec", {}).get("default") is True]
        selected = defaults[0] if len(defaults) == 1 else locations[0] if len(defaults) == 0 and len(locations) == 1 else None
    if selected is None:
        return fail("BSL_SELECTION", "Choose an existing BackupStorageLocation explicitly")
    storage = selected["metadata"]["name"]
    if selected.get("status", {}).get("phase") != "Available" or selected.get("spec", {}).get("accessMode") == "ReadOnly":
        return fail("BSL_NOT_READY", f"BackupStorageLocation {storage} is not Available and writable")

    velero_config = dpa.get("spec", {}).get("configuration", {}).get("velero", {})
    default_fs = velero_config.get("defaultVolumesToFsBackup", velero_config.get("defaultVolumesToFSBackup", False))
    if args.fs_backup or (not args.snapshot_volumes and default_fs):
        if velero_config.get("disableFsBackup"):
            return fail("FS_BACKUP_UNAVAILABLE", "DPA disables filesystem backup")
        try:
            agent = get_json("daemonset", "node-agent", "-n", args.namespace).get("status", {})
        except (RuntimeError, json.JSONDecodeError) as exc:
            return fail("FS_BACKUP_UNAVAILABLE", str(exc))
        if not agent.get("desiredNumberScheduled") or agent.get("numberReady") != agent.get("desiredNumberScheduled"):
            return fail("FS_BACKUP_UNAVAILABLE", "node-agent is not fully ready")

    cli = ["oc", "oadp", "-n", args.namespace, "schedule", "create", args.name,
           "--schedule", args.schedule, "--storage-location", storage,
           "--include-namespaces", ",".join(namespaces)]
    if args.ttl:
        cli.extend(["--ttl", args.ttl])
    if args.fs_backup:
        cli.extend(["--default-volumes-to-fs-backup=true", "--snapshot-volumes=false"])
    elif args.snapshot_volumes:
        cli.extend(["--default-volumes-to-fs-backup=false", "--snapshot-volumes=true"])
    if not args.run_immediately:
        cli.append("--skip-immediately=true")
    if args.paused:
        cli.append("--paused")

    preview = subprocess.run([*cli, "-o", "json"], capture_output=True, text=True)
    if preview.returncode:
        return fail("CLI_PREVIEW_FAILED", preview.stderr.strip() or "OADP CLI schedule preview failed")
    try:
        manifest = json.loads(preview.stdout)
    except json.JSONDecodeError:
        return fail("CLI_PREVIEW_FAILED", "OADP CLI returned invalid JSON")
    if (manifest.get("kind") != "Schedule" or manifest.get("metadata", {}).get("name") != args.name
            or manifest.get("metadata", {}).get("namespace") != args.namespace):
        return fail("INVALID_PREVIEW", "OADP CLI preview did not return the expected Schedule")
    schedule_spec = manifest.get("spec", {})
    template = schedule_spec.get("template", {})
    if (schedule_spec.get("schedule") != args.schedule
            or template.get("includedNamespaces") != namespaces
            or template.get("storageLocation") != storage
            or (not args.run_immediately and schedule_spec.get("skipImmediately") is not True)
            or (args.paused and schedule_spec.get("paused") is not True)):
        return fail("INVALID_PREVIEW", "OADP CLI preview does not match the requested schedule, namespaces, storage, or start behavior")

    result = {"created": False, "name": args.name, "namespace": args.namespace,
              "storage_location": storage, "manifest": manifest,
              "create_command": shlex.join(cli)}
    if args.emit_only:
        print(json.dumps(result))
        return 0
    for verb in ("create", "get"):
        if command("auth", "can-i", "-q", verb, "schedules.velero.io", "-n", args.namespace).returncode:
            result["required_permission"] = f"{verb} schedules.velero.io in {args.namespace}"
            print(json.dumps(result))
            return 0
    created = subprocess.run(cli, capture_output=True, text=True)
    if created.returncode:
        return fail("CREATE_FAILED", created.stderr.strip() or "OADP CLI could not create the Schedule")
    result["created"] = True
    result.pop("create_command")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
