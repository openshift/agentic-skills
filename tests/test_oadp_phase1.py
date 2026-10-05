"""Behavior tests for the remaining OADP Phase 1 skills using a fake oc."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FAKE_OC = r'''#!/usr/bin/env python3
import json, os, sys

state = json.load(open(os.environ["OADP_TEST_STATE"]))
args = sys.argv[1:]
with open(os.environ["OADP_TEST_CALLS"], "a") as calls:
    calls.write(json.dumps(args) + "\n")

def out(value):
    print(json.dumps(value) if not isinstance(value, str) else value)

def absent(resource):
    print(f"Error from server (NotFound): {resource} not found", file=sys.stderr)
    sys.exit(1)

if args[0] == "whoami":
    out("test-user")
elif args[0] == "auth":
    sys.exit(1 if state.get("deny_auth") else 0)
elif args[0] == "get":
    resource = args[1]
    if resource in state.get("deny_get", []):
        print("Forbidden", file=sys.stderr)
        sys.exit(1)
    if resource == "namespace":
        if args[2] in state.get("namespaces", []):
            out("namespace/" + args[2])
        else:
            absent(resource)
    elif resource == "dataprotectionapplication":
        out({"items": state.get("dpas", [])})
    elif resource == "deployment" and "-l" in args:
        out({"items": state.get("operators", [])})
    elif resource == "deployment":
        out(state.get("velero", {"status": {"availableReplicas": 1}}))
    elif resource == "daemonset":
        out(state.get("node_agent", {"status": {"desiredNumberScheduled": 2, "numberReady": 2}}))
    elif resource == "backupstoragelocation" and len(args) > 2 and not args[2].startswith("-"):
        out(state.get("bsl", {}))
    elif resource == "backupstoragelocation":
        out({"items": state.get("bsls", [])})
    elif resource == "backup":
        out(state.get("backup", {}))
    elif resource == "restore":
        out(state.get("restore", {}))
    elif resource == "schedule":
        out(state.get("schedule", {}))
    elif resource in ("podvolumebackups.velero.io", "podvolumerestores.velero.io",
                      "datauploads.velero.io", "datadownloads.velero.io",
                      "volumesnapshots.snapshot.storage.k8s.io",
                      "volumesnapshotcontents.snapshot.storage.k8s.io"):
        out({"items": state.get(resource, [])})
    else:
        print("unexpected get: " + " ".join(args), file=sys.stderr)
        sys.exit(2)
elif args[0] == "oadp":
    assert args[1] == "-n"
    namespace, kind, verb, name = args[2:6]
    assert verb == "create"
    preview = len(args) >= 2 and args[-2:] == ["-o", "json"]
    options = args[6:-2] if preview else args[6:]
    def value(flag, default=""):
        return options[options.index(flag) + 1] if flag in options else default
    sources = value("--include-namespaces").split(",")
    if kind == "schedule":
        manifest = {"apiVersion": "velero.io/v1", "kind": "Schedule",
                    "metadata": {"name": name, "namespace": namespace},
                    "spec": {"schedule": value("--schedule"),
                             "skipImmediately": "--skip-immediately=true" in options,
                             "paused": "--paused" in options,
                             "template": {"includedNamespaces": sources,
                                          "storageLocation": value("--storage-location")}}}
    elif kind == "restore":
        mappings = {}
        for pair in value("--namespace-mappings").split(","):
            if pair:
                src, dst = pair.split(":")
                mappings[src] = dst
        manifest = {"apiVersion": "velero.io/v1", "kind": "Restore",
                    "metadata": {"name": name, "namespace": namespace},
                    "spec": {"backupName": value("--from-backup"),
                             "includedNamespaces": sources, "namespaceMapping": mappings}}
    else:
        sys.exit(2)
    if preview:
        out(manifest)
    else:
        out("submitted")
else:
    print("unexpected oc: " + " ".join(args), file=sys.stderr)
    sys.exit(2)
'''


def fake_oc(tmp_path):
    oc = tmp_path / "oc"
    oc.write_text(FAKE_OC)
    oc.chmod(0o755)
    state_file = tmp_path / "state.json"
    calls_file = tmp_path / "calls.jsonl"
    state = {
        "namespaces": ["app", "other", "app-recovered"],
        "operators": [{"status": {"availableReplicas": 1}}],
        "dpas": [{"metadata": {"name": "dpa"}, "spec": {"configuration": {"velero": {}}},
                  "status": {"conditions": [{"type": "Reconciled", "status": "True"}]}}],
        "bsls": [{"metadata": {"name": "primary"}, "spec": {"default": True, "accessMode": "ReadWrite"},
                  "status": {"phase": "Available"}}],
        "bsl": {"status": {"phase": "Available"}},
        "backup": {"metadata": {"name": "app-backup"},
                   "spec": {"includedNamespaces": ["app"], "storageLocation": "primary"},
                   "status": {"phase": "Completed", "errors": 0}},
        "restore": {"spec": {"backupName": "app-backup", "namespaceMapping": {"app": "app-recovered"}},
                    "status": {"phase": "Completed", "errors": 0,
                               "progress": {"itemsRestored": 4, "totalItems": 4}}},
        "schedule": {"spec": {"schedule": "0 2 * * *", "paused": False},
                     "status": {"phase": "Enabled", "lastBackup": None}},
    }
    env = os.environ.copy()
    env["PATH"] = str(tmp_path) + os.pathsep + env["PATH"]
    env["OADP_TEST_STATE"] = str(state_file)
    env["OADP_TEST_CALLS"] = str(calls_file)

    def run(script, *args):
        state_file.write_text(json.dumps(state))
        result = subprocess.run(["python3", str(ROOT / script), *args], env=env,
                                capture_output=True, text=True, timeout=10, check=False)
        return result.returncode, json.loads(result.stdout), [json.loads(line) for line in calls_file.read_text().splitlines()]

    return state, run


class Phase1Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state, self.run_script = fake_oc(Path(tmp.name))

    def test_health_check_distinguishes_blockers_from_warnings(self):
        state, run = self.state, self.run_script
        code, result, _ = run("oadp/health-check/scripts/health_check.py")
        self.assertEqual(code, 0)
        self.assertTrue(result["ready"])
        state["bsls"][0]["status"]["phase"] = "Unavailable"
        state["node_agent"] = {"status": {"desiredNumberScheduled": 2, "numberReady": 0}}
        code, result, _ = run("oadp/health-check/scripts/health_check.py")
        self.assertEqual(code, 1)
        self.assertFalse(result["ready"])
        self.assertTrue(any(c["name"] == "storage_location" and c["status"] == "error" for c in result["checks"]))
        self.assertTrue(any(c["name"] == "node_agent" and c["status"] == "warn" for c in result["checks"]))
        state["dpas"][0]["spec"]["configuration"]["velero"]["defaultVolumesToFsBackup"] = True
        code, result, _ = run("oadp/health-check/scripts/health_check.py")
        self.assertEqual(code, 1)
        self.assertTrue(any(c["name"] == "node_agent" and c["status"] == "error" for c in result["checks"]))

    def test_schedule_preview_and_enabled_status(self):
        state, run = self.state, self.run_script
        script = "oadp/schedule-backup/scripts/create_schedule.py"
        args = ("--name", "daily", "--namespaces", "app,other", "--schedule", "0 2 * * *")
        code, result, calls = run(script, *args, "--emit-only")
        self.assertEqual(code, 0)
        self.assertFalse(result["created"])
        self.assertEqual(result["manifest"]["spec"]["template"]["includedNamespaces"], ["app", "other"])
        self.assertTrue(any("--skip-immediately=true" in c for c in calls if c[:1] == ["oadp"]))
        self.assertFalse(any(c[:1] == ["oadp"] and c[-2:] != ["-o", "json"] for c in calls))
        code, result, calls = run(script, *args, "--run-immediately")
        self.assertEqual(code, 0)
        self.assertTrue(result["created"])
        self.assertTrue(any(c[:1] == ["oadp"] and c[-2:] != ["-o", "json"] for c in calls))
        code, result, _ = run("oadp/schedule-backup/scripts/verify_schedule.py", "--name", "daily", "--timeout", "0")
        self.assertEqual(code, 0)
        self.assertTrue(result["ready"])
        self.assertIsNone(result["last_backup"])
        state["schedule"]["status"] = {"phase": "FailedValidation", "validationErrors": ["invalid cron"]}
        code, result, _ = run("oadp/schedule-backup/scripts/verify_schedule.py", "--name", "daily", "--timeout", "0")
        self.assertEqual(code, 0)
        self.assertFalse(result["ready"])
        self.assertEqual(result["validation_errors"], ["invalid cron"])

    def test_schedule_blocks_unavailable_storage(self):
        state, run = self.state, self.run_script
        state["bsls"][0]["status"]["phase"] = "Unavailable"
        code, result, calls = run("oadp/schedule-backup/scripts/create_schedule.py",
                                  "--name", "daily", "--namespaces", "app", "--schedule", "0 2 * * *")
        self.assertEqual(code, 1)
        self.assertEqual(result["code"], "BSL_NOT_READY")
        self.assertFalse(any(c[:1] == ["oadp"] for c in calls))

    def test_restore_requires_explicit_target_and_verifies_volume_results(self):
        state, run = self.state, self.run_script
        script = "oadp/restore-backup/scripts/create_restore.py"
        code, result, calls = run(script, "--from-backup", "app-backup", "--name", "recover")
        self.assertEqual(code, 1)
        self.assertEqual(result["code"], "IN_PLACE_NOT_ALLOWED")
        self.assertFalse(any(c[:1] == ["oadp"] for c in calls))
        code, result, _ = run(script, "--from-backup", "app-backup", "--name", "recover",
                              "--namespace-mappings", "app:app-recovered")
        self.assertEqual(code, 1)
        self.assertEqual(result["code"], "TARGET_EXISTS")
        state["namespaces"].remove("app-recovered")
        code, result, _ = run(script, "--from-backup", "app-backup", "--name", "recover",
                              "--namespace-mappings", "app:app-recovered")
        self.assertEqual(code, 0)
        self.assertTrue(result["created"])
        code, result, _ = run("oadp/restore-backup/scripts/monitor_restore.py", "--name", "recover", "--timeout", "0")
        self.assertEqual(code, 0)
        self.assertTrue(result["terminal"])
        state["datadownloads.velero.io"] = [{"metadata": {"name": "volume-1"}, "status": {"phase": "Failed"}}]
        code, result, _ = run("oadp/restore-backup/scripts/verify_restore.py", "--name", "recover")
        self.assertEqual(code, 0)
        self.assertFalse(result["succeeded"])
        self.assertEqual(result["volume_restores"]["data_downloads"], {"Failed": 1})

    def test_restore_rejects_partial_backup_without_explicit_choice(self):
        state, run = self.state, self.run_script
        state["backup"]["status"]["phase"] = "PartiallyFailed"
        code, result, calls = run("oadp/restore-backup/scripts/create_restore.py",
                                  "--from-backup", "app-backup", "--name", "recover",
                                  "--namespace-mappings", "app:new-target")
        self.assertEqual(code, 1)
        self.assertEqual(result["code"], "BACKUP_NOT_RESTORABLE")
        self.assertFalse(any(c[:1] == ["oadp"] for c in calls))
        code, result, _ = run("oadp/restore-backup/scripts/create_restore.py",
                              "--from-backup", "app-backup", "--name", "recover",
                              "--namespace-mappings", "app:new-target", "--allow-partially-failed", "--emit-only")
        self.assertEqual(code, 0)
        self.assertFalse(result["created"])
        self.assertEqual(result["source_backup_phase"], "PartiallyFailed")

    def test_restore_rejects_expired_backup(self):
        state, run = self.state, self.run_script
        state["backup"]["status"]["expiration"] = "2020-01-01T00:00:00Z"
        code, result, calls = run("oadp/restore-backup/scripts/create_restore.py",
                                  "--from-backup", "app-backup", "--name", "recover",
                                  "--namespace-mappings", "app:new-target")
        self.assertEqual(code, 1)
        self.assertEqual(result["code"], "BACKUP_EXPIRED")
        self.assertFalse(any(c[:1] == ["oadp"] for c in calls))

    def test_diagnose_reports_csi_and_data_mover_evidence(self):
        state, run = self.state, self.run_script
        state["backup"]["status"].update({"phase": "PartiallyFailed", "errors": 1,
                                            "csiVolumeSnapshotsAttempted": 2, "csiVolumeSnapshotsCompleted": 1})
        state["datauploads.velero.io"] = [{"metadata": {"name": "upload-1"},
                                              "status": {"phase": "Failed", "message": "repository unavailable"}}]
        state["volumesnapshots.snapshot.storage.k8s.io"] = [
            {"metadata": {"name": "snapshot-1", "namespace": "app"},
             "status": {"readyToUse": False, "error": {"message": "CSI driver timed out"}}}]
        code, result, calls = run("oadp/diagnose/scripts/diagnose.py", "--kind", "backup", "--name", "app-backup")
        self.assertEqual(code, 0)
        self.assertGreaterEqual({finding["category"] for finding in result["findings"]},
                                {"snapshot", "csi_snapshot", "data_mover"})
        self.assertEqual(result["volume_operations"]["data_uploads"][0]["message"], "repository unavailable")
        self.assertFalse(any(c[:1] == ["oadp"] for c in calls))

    def test_diagnose_restore_reports_missing_inspection(self):
        state, run = self.state, self.run_script
        state["deny_get"] = ["datadownloads.velero.io"]
        code, result, _ = run("oadp/diagnose/scripts/diagnose.py", "--kind", "restore", "--name", "recover")
        self.assertEqual(code, 0)
        self.assertIsNone(result["volume_operations"]["data_downloads"])
        self.assertEqual(len(result["inspection_errors"]), 1)

    def test_diagnose_restore_inspects_restore_labeled_csi_snapshot(self):
        state, run = self.state, self.run_script
        state["backup"]["status"].update({"csiVolumeSnapshotsAttempted": 1,
                                            "csiVolumeSnapshotsCompleted": 1})
        state["volumesnapshots.snapshot.storage.k8s.io"] = [
            {"metadata": {"name": "recovered-snapshot", "namespace": "app-recovered"},
             "status": {"readyToUse": False, "error": {"message": "snapshot restore timed out"}}}]
        code, result, calls = run("oadp/diagnose/scripts/diagnose.py", "--kind", "restore", "--name", "recover")
        self.assertEqual(code, 0)
        self.assertIn("csi_snapshot", {finding["category"] for finding in result["findings"]})
        self.assertTrue(any("velero.io/restore-name=recover" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
