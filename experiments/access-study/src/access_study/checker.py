"""Real checks in bwrap, adapted from curation/tools/reproduce.py, not imported.

No downloaded program is imported by the host. Read-only system/source/adapter
mounts, isolated PID/network namespaces, clean environment, bounded subprocess.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from .common import ROOT, canonical, sha, inventory, subject, write, settings


def environment():
    command = ["/usr/bin/python3", "-I", "-S", "-c", "import sys; print(sys.version)"]
    return {"python": subprocess.check_output(command, text=True).strip(),
            "interpreter_sha256": sha(Path("/usr/bin/python3").resolve().read_bytes()),
            "platform": os.uname().sysname + " " + os.uname().release + " " + os.uname().machine,
            "dependency_contract": "CPython standard library only; system shared libraries; no site packages",
            "environment_bound": "interpreter binary/version and host kernel; stdlib/system mounts trusted, not exhaustively hashed"}


def command(source, adapter, case, subject_hash, cfg):
    worker = Path(__file__).with_name("check_worker.py")
    return ["/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
            "--cap-drop", "ALL", "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
            "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/tmp", "--setenv", "LANG", "C.UTF-8",
            "--chdir", "/tmp", "--ro-bind", str(source), "/source", "--ro-bind", str(adapter.parent), "/tests",
            "--ro-bind", str(adapter), "/adapter.py",
            "--ro-bind", str(worker), "/worker.py", "/usr/bin/prlimit",
            f"--as={cfg['address_space_bytes']}", f"--cpu={cfg['cpu_seconds']}",
            f"--fsize={cfg['file_size_bytes']}", f"--nofile={cfg['open_fds']}", "--core=0", "--",
            "/usr/bin/python3", "-I", "-S", "-B", "/worker.py", "--check", "functional",
            "--case", case, "--subject", subject_hash]


def check(workspace, case, adapter, binding, out, deadline=None):
    cfg = settings()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    before = inventory(workspace)
    manifest = subject(before)
    subject_hash = sha(canonical(manifest))
    if sha(Path(adapter).read_bytes()) != binding["adapter_sha256"]:
        raise RuntimeError("Adapter changed")
    if inventory(Path(adapter).parent) != binding["test_files"]:
        raise RuntimeError("Test inputs changed")
    if sha(Path(__file__).with_name("check_worker.py").read_bytes()) != binding["worker_sha256"]:
        raise RuntimeError("Check worker changed")
    if environment() != binding["environment"]:
        raise RuntimeError("Runtime binding changed")
    started = time.monotonic()
    timeout = min(cfg["check_seconds"], deadline - started) if deadline else cfg["check_seconds"]
    if timeout <= 0:
        raise TimeoutError("No remaining check time")
    cmd = command(Path(workspace) / "source", Path(adapter), case, subject_hash, cfg)
    timed_out = False
    # prlimit wraps the entire sandbox as well, so output files are size-bounded.
    outer = ["/usr/bin/prlimit", f"--fsize={cfg['file_size_bytes']}", "--core=0", "--"] + cmd
    with (out / "stdout.txt").open("wb") as stdout, (out / "stderr.txt").open("wb") as stderr:
        process = subprocess.Popen(outer, cwd="/tmp", env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                                   stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            # Always reap the entire launcher group, not just the immediate child.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    raw_stdout = (out / "stdout.txt").read_text(errors="replace")
    raw_stderr = (out / "stderr.txt").read_text(errors="replace")
    try:
        parsed = json.loads(raw_stdout)
    except ValueError:
        parsed = None
    result = {"id": out.name, "check": "functional", "scope": cfg["scope"],
              "subject_manifest": manifest, "subject_sha256": subject_hash, "binding": binding,
              "outcome": parsed.get("outcome", "unknown") if isinstance(parsed, dict) else "unknown",
              "complete": not timed_out and process.returncode in (0, 1) and parsed is not None,
              "raw": {"stdout": raw_stdout, "stderr": raw_stderr, "parsed": parsed,
                      "exit_code": process.returncode, "timed_out": timed_out,
                      "command_template": ["bwrap", "/worker.py", "--check", "functional", "--case", case,
                                           "--subject", subject_hash]},
              "runtime_seconds": time.monotonic() - started}
    write(out / "receipt.json", {"command": outer, "timeout_seconds": timeout, "evidence": result})
    if inventory(workspace) != before:
        raise RuntimeError("Readonly check changed release files")
    return result
