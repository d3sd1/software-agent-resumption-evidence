"""Sandbox-only adapter wrapper. Emits exactly one bound functional result."""
import argparse
import json
import os
from pathlib import Path
import socket
import resource
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", choices=["functional"], required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--subject", required=True)
    args = parser.parse_args()
    assert sys.flags.isolated and sys.flags.no_site
    assert not Path("/home").exists() and not Path("/root").exists()
    assert set(os.environ) <= {"PATH", "HOME", "LANG", "PWD", "LC_CTYPE"}
    assert all(name == "lo" for _, name in socket.if_nameindex())
    mounts = Path("/proc/self/mountinfo").read_text()
    for mount in ("/usr", "/source", "/tests", "/adapter.py", "/worker.py"):
        rows = [row.split() for row in mounts.splitlines() if row.split()[4] == mount]
        assert rows and all("ro" in row[5].split(",") for row in rows), mount
    limits = {name: resource.getrlimit(getattr(resource, name)) for name in
              ("RLIMIT_AS", "RLIMIT_CPU", "RLIMIT_FSIZE", "RLIMIT_NOFILE", "RLIMIT_CORE")}
    assert all(soft != resource.RLIM_INFINITY for soft, hard in limits.values())
    isolation = {"home_visible": False, "root_visible": False, "environment": dict(os.environ),
                 "interfaces": socket.if_nameindex(), "limits": limits, "mountinfo": mounts}
    process = subprocess.run(["/usr/bin/python3", "-I", "-S", "-B", "/adapter.py", args.case],
                             capture_output=True, text=True, check=False)
    rows = [json.loads(line[12:]) for line in process.stdout.splitlines()
            if line.startswith("RESULT_JSON ")]
    result = rows[0] if len(rows) == 1 else None
    complete = (isinstance(result, dict) and result.get("case") == args.case
                and type(result.get("tests_run")) is int and result["tests_run"] > 0
                and result.get("skipped") == [] and process.returncode in (0, 1))
    passed = complete and result.get("success") is True and process.returncode == 0
    failed = complete and result.get("success") is False and process.returncode == 1
    outcome = "pass" if passed else "fail" if failed else "unknown"
    record = {"check": args.check, "scope": "public-regression-functional-v1",
              "subject_sha256": args.subject, "outcome": outcome,
              "case": args.case, "adapter_returncode": process.returncode,
              "adapter_stdout": process.stdout, "adapter_stderr": process.stderr,
              "adapter_result": result, "isolation": isolation}
    print(json.dumps(record, sort_keys=True))
    return 0 if passed else 1 if failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
