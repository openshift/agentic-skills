#!/usr/bin/env python3
"""Wait for a Velero Schedule to become Enabled, Paused, or FailedValidation."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--namespace", default=os.getenv("OADP_NAMESPACE", "openshift-adp"))
    args = parser.parse_args()
    if shutil.which("oc") is None:
        print(json.dumps({"error": True, "code": "MISSING_TOOL", "message": "oc is not available on PATH"}))
        return 1
    if args.timeout < 0 or args.interval <= 0:
        print(json.dumps({"error": True, "code": "INVALID_TIME", "message": "Use a non-negative timeout and positive interval"}))
        return 1
    deadline = time.monotonic() + args.timeout
    while True:
        response = subprocess.run(["oc", "get", "schedule", args.name, "-n", args.namespace, "-o", "json"],
                                  capture_output=True, text=True)
        if response.returncode:
            print(json.dumps({"error": True, "code": "READ_FAILED", "message": response.stderr.strip() or "Cannot read Schedule"}))
            return 1
        try:
            schedule = json.loads(response.stdout)
        except json.JSONDecodeError:
            print(json.dumps({"error": True, "code": "INVALID_JSON", "message": "Schedule API returned invalid JSON"}))
            return 1
        phase = schedule.get("status", {}).get("phase", "New")
        paused = schedule.get("spec", {}).get("paused", False)
        terminal = phase in ("Enabled", "FailedValidation") or paused
        if terminal or time.monotonic() >= deadline:
            result = {"name": args.name, "namespace": args.namespace, "phase": phase,
                      "paused": paused, "ready": phase == "Enabled" and not paused,
                      "timed_out": not terminal, "schedule": schedule.get("spec", {}).get("schedule"),
                      "last_backup": schedule.get("status", {}).get("lastBackup"),
                      "validation_errors": schedule.get("status", {}).get("validationErrors", []),
                      "guidance": "Check OADP CLI schedule describe and the first created Backup before claiming protection"}
            print(json.dumps(result))
            return 0
        time.sleep(min(args.interval, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    sys.exit(main())
