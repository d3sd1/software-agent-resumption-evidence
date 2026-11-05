"""Generate real local predecessor outputs, then apply explicit resumption mutations."""
import platform
import subprocess
import sys
import time
from common import ROOT, dependencies, digest, read_json, source, stamp, write_json


def execute_check(candidate, check_name, available, config, remaining_seconds=None):
    command = [sys.executable, "-I", str(ROOT / "checker.py"), "--candidate", str(candidate),
               "--check", check_name]
    if not available:
        command.append("--unavailable")
    started = time.perf_counter()
    timeout = config["check_timeout_seconds"]
    if remaining_seconds is not None:
        timeout = min(timeout, remaining_seconds)
    if timeout <= 0:
        raise TimeoutError("No remaining session time for check subprocess")
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    parsed = __import__("json").loads(completed.stdout)
    return {"command_template": ["<venv-python>", "-I", "checker.py", "--candidate",
                                 "<frozen-snapshot>", "--check", check_name] +
                                ([] if available else ["--unavailable"]),
            "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr,
            "runtime_seconds": time.perf_counter() - started, "parsed": parsed}


def evidence_record(identifier, raw, deps, config, provenance):
    result = raw["parsed"]
    return {"id": identifier, "subject_sha256": result["candidate_sha256"],
            "criterion_version": config["criteria"]["version"], "scope": result["scope"],
            "outcome": result["outcome"], "dependencies": deps,
            "check": result["check"], "observed_at": stamp(), "provenance": provenance,
            "raw": raw, "limits": result.get("limitation", "deterministic local functional examples only")}


def generate():
    config = read_json(ROOT / "config.json")
    spec = read_json(ROOT / "fixture-manifest.json")
    destination = ROOT / config["fixture_root"]
    if destination.exists():
        raise RuntimeError("Fixtures already exist; refusing to overwrite retained evidence")
    destination.mkdir()
    manifest = {"created_at": stamp(), "python": platform.python_version(),
                "config_sha256": digest((ROOT / "config.json").read_bytes()), "fixtures": {}}
    for family, settings in spec["families"].items():
        folder = destination / family
        folder.mkdir()
        predecessor = folder / "predecessor.py"
        predecessor.write_text(source(), encoding="utf-8")
        raw = execute_check(predecessor, settings["predecessor_check"],
                            settings["real_check_available"], config)
        if raw["exit_code"] != 0 or raw["parsed"]["outcome"] != "pass":
            raise RuntimeError(f"Unexpected predecessor failure: {family}")
        write_json(folder / "predecessor-check.json", raw)
        record = evidence_record("predecessor-001", raw, dependencies(), config, "predecessor-check.json")
        current = source(settings["current_multiplier"])
        (folder / "app.py").write_text(current, encoding="utf-8")
        fixture = {"family": family, "contract": config["criteria"], "dependencies": dependencies(),
                   "policy": {"check": True, "repair": True, "release": settings["release_authorized"]},
                   "initial_policy": spec["policy_initial"], "real_check_available": settings["real_check_available"],
                   "predecessor_hash": digest(source()), "initial_hash": digest(current), "evidence": [record],
                   "git_state": "No Git history created. Dirty means current bytes differ from retained predecessor.py.",
                   "predecessor_kind": "harness-generated evidence; no originating model call"}
        write_json(folder / "fixture.json", fixture)
        manifest["fixtures"][family] = {p.name: digest(p.read_bytes()) for p in sorted(folder.iterdir())}
    write_json(destination / "manifest.json", manifest)
    print(f"Generated {len(manifest['fixtures'])} fixtures with real predecessor subprocess logs")


if __name__ == "__main__":
    generate()
