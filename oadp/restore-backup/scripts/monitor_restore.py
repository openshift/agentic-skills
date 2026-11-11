#!/usr/bin/env python3
"""Poll a Velero Restore until it finishes or times out."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time


TERMINAL = {"Completed", "PartiallyFailed", "Failed", "FailedValidation"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--interval", type=int, default=15)
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
        response = subprocess.run(["oc", "get", "restore", args.name, "-n", args.namespace, "-o", "json"],
                                  capture_output=True, text=True)
        if response.returncode:
            print(json.dumps({"error": True, "code": "READ_FAILED", "message": response.stderr.strip() or "Cannot read Restore"}))
            return 1
        try:
            restore = json.loads(response.stdout)
        except json.JSONDecodeError:
            print(json.dumps({"error": True, "code": "INVALID_JSON", "message": "Restore API returned invalid JSON"}))
            return 1
        status = restore.get("status", {})
        phase = status.get("phase", "New")
        if phase in TERMINAL or time.monotonic() >= deadline:
            print(json.dumps({"name": args.name, "namespace": args.namespace, "phase": phase,
                              "terminal": phase in TERMINAL, "timed_out": phase not in TERMINAL,
                              "progress": status.get("progress", {}), "warnings": status.get("warnings", 0),
                              "errors": status.get("errors", 0), "failure_reason": status.get("failureReason"),
                              "completion_timestamp": status.get("completionTimestamp")}))
            return 0
        time.sleep(min(args.interval, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    sys.exit(main())
