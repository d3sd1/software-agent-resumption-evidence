"""Trusted construction utilities; no model calls or decision oracle."""
import json
import subprocess
import sys
import time
from common import ROOT, dependencies, digest, read_json, stamp, write_json


def config():
    return read_json(ROOT / "config-v2.json")


def package_bytes(package):
    return json.dumps(package, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def source(multiplier):
    return config()["source_template"].format(multiplier=multiplier)


def opaque(label, prefix="c"):
    return prefix + digest(label)[:24]


def capture_check(folder, package, contract, name, identifier, remaining=None):
    settings = config()
    timeout = settings["check_timeout_seconds"] if remaining is None else min(settings["check_timeout_seconds"], remaining)
    if timeout <= 0:
        raise TimeoutError("No remaining check time")
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = folder / (identifier + ".json")
    payload = package_bytes(package)
    snapshot.write_bytes(payload)
    command = [sys.executable, "-I", str(ROOT / "checker.py"), "--snapshot", str(snapshot),
               "--check", name, "--target", str(contract["target_percent"]), "--cases", json.dumps(contract["cases"])]
    start = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    runtime = time.perf_counter() - start
    parsed = json.loads(result.stdout)
    raw = {"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode,
           "runtime_seconds": runtime, "parsed": parsed,
           "command_template": ["<venv-python>", "-I", "checker.py", "--snapshot", "<immutable-json>",
                                "--check", name, "--target", str(contract["target_percent"]), "--cases", json.dumps(contract["cases"])]}
    write_json(folder / (identifier + "-raw.json"), raw)
    return {"id": identifier, "complete": True, "subject_sha256": digest(payload),
            "criterion_version": contract["version"], "dependencies": dependencies(),
            "scope": parsed["scope"], "outcome": parsed["outcome"], "check": name,
            "observed_at": stamp(), "raw": raw, "provenance": identifier + "-raw.json"}
