#!/usr/bin/env python3
"""Create a guarded OADP restore from a completed Backup."""

import argparse
import datetime
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


def parse_mappings(text):
    mappings = {}
    if not text:
        return mappings
    for pair in text.split(","):
        parts = pair.split(":")
        if len(parts) != 2 or not all(valid_name(part) for part in parts):
            raise ValueError("Namespace mappings must be source:target pairs with DNS label names")
        source, target = parts
        if source in mappings:
            raise ValueError(f"Duplicate mapping for {source}")
        mappings[source] = target
    return mappings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-backup", required=True)
    parser.add_argument("--name")
    parser.add_argument("--include-namespaces", help="Comma-separated source namespaces, required for all-namespace backups")
    parser.add_argument("--namespace-mappings", help="Comma-separated source:target pairs")
    parser.add_argument("--allow-in-place", action="store_true", help="Allow restoring into source namespaces")
    parser.add_argument("--allow-existing-target", action="store_true", help="Allow mapped target namespaces that already exist")
    parser.add_argument("--allow-partially-failed", action="store_true")
    parser.add_argument("--emit-only", action="store_true")
    parser.add_argument("--namespace", default=os.getenv("OADP_NAMESPACE", "openshift-adp"))
    args = parser.parse_args()
    if shutil.which("oc") is None:
        return fail("MISSING_TOOL", "oc is not available on PATH")

    if not valid_name(args.from_backup):
        return fail("INVALID_NAME", "Backup name must be a DNS label of at most 63 characters")
    name = args.name or f"{args.from_backup[:38]}-restore-{datetime.datetime.now(datetime.timezone.utc):%Y%m%d%H%M%S}"
    if not valid_name(name):
        return fail("INVALID_NAME", "Restore name must be a DNS label of at most 63 characters")
    try:
        mappings = parse_mappings(args.namespace_mappings)
    except ValueError as exc:
        return fail("INVALID_MAPPING", str(exc))
    if command("whoami").returncode:
        return fail("AUTH_FAILED", "Log in to the OpenShift cluster first")
    try:
        backup = get_json("backup", args.from_backup, "-n", args.namespace)
        velero = get_json("deployment", "velero", "-n", args.namespace)
        dpas = get_json("dataprotectionapplication", "-n", args.namespace).get("items", [])
    except (RuntimeError, json.JSONDecodeError) as exc:
        return fail("PREFLIGHT_FAILED", str(exc))
    if len(dpas) != 1:
        return fail("DPA_SELECTION", "Expected one DataProtectionApplication in the OADP namespace")
    reconciled = [c for c in dpas[0].get("status", {}).get("conditions", []) if c.get("type") == "Reconciled"]
    if not reconciled or reconciled[-1].get("status") != "True":
        return fail("DPA_NOT_READY", "DataProtectionApplication is not reconciled")
    phase = backup.get("status", {}).get("phase")
    if phase != "Completed" and not (phase == "PartiallyFailed" and args.allow_partially_failed):
        return fail("BACKUP_NOT_RESTORABLE", f"Backup phase is {phase or 'New'}; require Completed or explicitly allow PartiallyFailed")
    if backup.get("status", {}).get("errors", 0) and not args.allow_partially_failed:
        return fail("BACKUP_NOT_RESTORABLE", "Backup has recorded errors; inspect them before restoring")
    expiration = backup.get("status", {}).get("expiration")
    if expiration:
        try:
            expires_at = datetime.datetime.fromisoformat(expiration.replace("Z", "+00:00"))
            if expires_at <= datetime.datetime.now(datetime.timezone.utc):
                return fail("BACKUP_EXPIRED", "Backup retention has expired; confirm backup data still exists before restoring")
        except ValueError:
            return fail("INVALID_BACKUP_STATUS", "Backup expiration timestamp is invalid")
    if velero.get("status", {}).get("availableReplicas", 0) < 1:
        return fail("VELERO_NOT_READY", "Velero deployment has no available replicas")
    location = (backup.get("spec", {}).get("storageLocation")
                or backup.get("metadata", {}).get("labels", {}).get("velero.io/storage-location"))
    if not location:
        try:
            locations = get_json("backupstoragelocation", "-n", args.namespace).get("items", [])
        except (RuntimeError, json.JSONDecodeError) as exc:
            return fail("STORAGE_UNKNOWN", str(exc))
        defaults = [b for b in locations if b.get("spec", {}).get("default") is True]
        selected = defaults[0] if len(defaults) == 1 else locations[0] if len(defaults) == 0 and len(locations) == 1 else None
        if selected:
            location = selected.get("metadata", {}).get("name")
    if not location:
        return fail("STORAGE_UNKNOWN", "Cannot identify the Backup storage location; select a Backup with a known BSL")
    try:
        bsl = get_json("backupstoragelocation", location, "-n", args.namespace)
    except (RuntimeError, json.JSONDecodeError) as exc:
        return fail("BSL_NOT_READY", str(exc))
    if bsl.get("status", {}).get("phase") != "Available":
        return fail("BSL_NOT_READY", f"BackupStorageLocation {location} is not Available")
    backup_spec = backup.get("spec", {})
    needs_agent = bool(backup_spec.get("defaultVolumesToFsBackup") or backup_spec.get("snapshotMoveData"))
    try:
        for kind in ("podvolumebackups.velero.io", "datauploads.velero.io"):
            items = get_json(kind, "-n", args.namespace,
                             "-l", f"velero.io/backup-name={args.from_backup}").get("items", [])
            needs_agent = needs_agent or bool(items)
    except (RuntimeError, json.JSONDecodeError) as exc:
        return fail("VOLUME_PATH_UNKNOWN", f"Cannot inspect the Backup volume path: {exc}")
    if needs_agent:
        try:
            agent = get_json("daemonset", "node-agent", "-n", args.namespace).get("status", {})
        except (RuntimeError, json.JSONDecodeError) as exc:
            return fail("NODE_AGENT_NOT_READY", str(exc))
        if not agent.get("desiredNumberScheduled") or agent.get("numberReady") != agent.get("desiredNumberScheduled"):
            return fail("NODE_AGENT_NOT_READY", "node-agent is not fully ready for volume restoration")

    backed_up = backup.get("spec", {}).get("includedNamespaces") or []
    if args.include_namespaces:
        sources = args.include_namespaces.split(",")
    elif backed_up and "*" not in backed_up:
        sources = backed_up
    else:
        return fail("SOURCE_SELECTION", "Specify source namespaces for a backup that includes all namespaces")
    if not sources or any(not valid_name(source) for source in sources) or len(set(sources)) != len(sources):
        return fail("SOURCE_SELECTION", "Source namespaces must be unique DNS labels")
    if backed_up and "*" not in backed_up and any(source not in backed_up for source in sources):
        return fail("SOURCE_SELECTION", "A requested source namespace is not in the Backup spec")
    excluded = backup.get("spec", {}).get("excludedNamespaces") or []
    if any(source in excluded for source in sources):
        return fail("SOURCE_SELECTION", "A requested source namespace was excluded from the Backup")
    if any(source not in sources for source in mappings):
        return fail("INVALID_MAPPING", "A mapping names a source namespace that is not selected")
    if not args.allow_in_place and any(source not in mappings or mappings[source] == source for source in sources):
        return fail("IN_PLACE_NOT_ALLOWED", "Map every source namespace to a different target, or explicitly allow an in-place restore")
    targets = [mappings.get(source, source) for source in sources]
    if len(set(targets)) != len(targets):
        return fail("INVALID_MAPPING", "Two source namespaces cannot map to the same target")
    for source, target in zip(sources, targets):
        response = command("get", "namespace", target, "-o", "name")
        if response.returncode == 0 and target != source and not args.allow_existing_target:
            return fail("TARGET_EXISTS", f"Target namespace {target} exists; explicitly allow an existing target")
        if response.returncode != 0 and "NotFound" not in response.stderr and "not found" not in response.stderr.lower():
            return fail("TARGET_UNKNOWN", f"Cannot determine whether target namespace {target} exists: {response.stderr.strip()}")

    cli = ["oc", "oadp", "-n", args.namespace, "restore", "create", name,
           "--from-backup", args.from_backup,
           "--include-namespaces", ",".join(sources)]
    if mappings:
        cli.extend(["--namespace-mappings", ",".join(f"{source}:{target}" for source, target in mappings.items())])
    preview = subprocess.run([*cli, "-o", "json"], capture_output=True, text=True)
    if preview.returncode:
        return fail("CLI_PREVIEW_FAILED", preview.stderr.strip() or "OADP CLI restore preview failed")
    try:
        manifest = json.loads(preview.stdout)
    except json.JSONDecodeError:
        return fail("CLI_PREVIEW_FAILED", "OADP CLI returned invalid JSON")
    if (manifest.get("kind") != "Restore" or manifest.get("metadata", {}).get("name") != name
            or manifest.get("metadata", {}).get("namespace") != args.namespace
            or manifest.get("spec", {}).get("backupName") != args.from_backup):
        return fail("INVALID_PREVIEW", "OADP CLI preview did not return the expected Restore")
    restore_spec = manifest.get("spec", {})
    if restore_spec.get("includedNamespaces") != sources or (restore_spec.get("namespaceMapping") or {}) != mappings:
        return fail("INVALID_PREVIEW", "OADP CLI preview does not match the requested source namespaces and target mapping")
    result = {"created": False, "name": name, "backup_name": args.from_backup,
              "namespace": args.namespace, "source_namespaces": sources,
              "target_namespaces": targets, "manifest": manifest,
              "create_command": shlex.join(cli), "source_backup_phase": phase}
    if args.emit_only:
        print(json.dumps(result))
        return 0
    for verb in ("create", "get"):
        if command("auth", "can-i", "-q", verb, "restores.velero.io", "-n", args.namespace).returncode:
            result["required_permission"] = f"{verb} restores.velero.io in {args.namespace}"
            print(json.dumps(result))
            return 0
    created = subprocess.run(cli, capture_output=True, text=True)
    if created.returncode:
        return fail("CREATE_FAILED", created.stderr.strip() or "OADP CLI could not create the Restore")
    result["created"] = True
    result.pop("create_command")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
