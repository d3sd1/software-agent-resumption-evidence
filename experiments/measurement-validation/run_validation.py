#!/usr/bin/env python3
"""Offline scripted measurement validation. Writes only inside this directory."""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
EXPERIMENTS = HERE.parent
EXPANSION = EXPERIMENTS / "expansion"


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_hashes():
    result = {}
    for root, dirs, files in os.walk(EXPERIMENTS):
        dirs[:] = sorted(d for d in dirs if d not in {"measurement-validation", ".venv", "__pycache__", ".git"})
        for name in sorted(files):
            path = Path(root) / name
            if not path.is_symlink():
                result[str(path.relative_to(EXPERIMENTS))] = sha(path)
    return result


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.append({"test": test.id(), "status": "PASS"})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records.append({"test": test.id(), "status": "FAIL", "traceback": self._exc_info_to_string(err, test)})

    def addError(self, test, err):
        super().addError(test, err)
        self.records.append({"test": test.id(), "status": "ERROR", "traceback": self._exc_info_to_string(err, test)})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.records.append({"test": test.id(), "status": "SKIP", "reason": reason})


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def worker(group, output):
    # Audit hooks supplement the inspected, allowlisted test entry points. No client executable is allowed.
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    def audit(event, args):
        if event in {"socket.connect", "socket.getaddrinfo"}:
            raise RuntimeError("Network is disabled in measurement-validation workers")
        if event == "subprocess.Popen":
            command = args[1]
            if not isinstance(command, (list, tuple)) or Path(command[0]).resolve() != Path(sys.executable).resolve():
                raise RuntimeError("Only local Python test subprocesses are allowed")
            allowed = {str(EXPERIMENTS / "checker.py"), str(EXPERIMENTS / "mcp_server.py"), str(EXPANSION / "checker.py")}
            fake = [str(p) for p in output.rglob("fake_client.py")]
            if not any(str(arg) in allowed or str(arg) in fake for arg in command[1:]):
                raise RuntimeError("Subprocess entry point is not an inspected local test utility")
    sys.addaudithook(audit)
    source = EXPERIMENTS if group == "pilot" else EXPANSION
    sys.path.insert(0, str(source))
    local_temp = output / "temporary"
    local_temp.mkdir()
    original_temp = tempfile.TemporaryDirectory
    def redirected_temp(*args, **kwargs):
        kwargs["dir"] = local_temp
        return original_temp(*args, **kwargs)
    modules = []
    with patch("tempfile.TemporaryDirectory", side_effect=redirected_temp):
        if group == "pilot":
            modules = [load_module("reused_pilot_tests", EXPERIMENTS / "tests.py"),
                       load_module("reused_audit_tests", EXPERIMENTS / "tests_audit_fixes.py")]
        else:
            # Path rendering only: score() requires event paths relative to its ROOT.
            # All fixtures/config/checkers still resolve to the unchanged expansion directory.
            import evaluate
            evaluate.ROOT = EXPERIMENTS
            if group == "expansion":
                modules = [load_module("reused_expansion_tests", EXPANSION / "tests.py")]
            else:
                module = load_module("focused_tests", HERE / "focused_tests.py")
                module.OUTPUT = output / "scripted-cases"
                module.OUTPUT.mkdir()
                modules = [module]
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in modules)
        result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2, resultclass=RecordedResult).run(suite)
    save(output / "test-results.json", {"group": group, "tests_run": result.testsRun,
         "successful": result.wasSuccessful(), "records": result.records,
         "temporary_directory_redirection": "All test TemporaryDirectory calls were redirected under this run directory.",
         "path_only_patch": None if group == "pilot" else "evaluate.ROOT = experiments (relative event-path rendering only)"})
    if group == "focused":
        save(output / "observations.json", modules[0].OBSERVATIONS)
    return 0 if result.wasSuccessful() else 1


SUPPLEMENTAL = [
    {"capability": "Mock scope and unavailable checks", "vector": "Invalid: mock-only with unavailable real check. Positive counterpart: actual failing check, bounded repair, passing real check and release.",
     "expectation": "Mock/unavailable yields unknown, exit 3 and no supported release. Actual check yields fail/exit 1 before repair and pass plus supported release after repair.",
     "tests": ["test_mock_and_unavailable_are_not_pass", "test_actual_check_and_repair"], "source": "tests.py"},
    {"capability": "Historical source and raw-record immutability", "vector": "Valid: compare protected pilot files and preserved pilot source against stored SHA-256 manifests; re-score historical records without live dependency lookup. Negative counterpart: synthetic corrupted sink in focused snapshot-tampered case.",
     "expectation": "Every protected hash equals its retained manifest entry; selected historical metrics match existing results; a changed scripted sink is rejected separately.",
     "tests": ["test_preserved_pilot_source_and_raw_files", "test_pilot_reanalysis_matches_original_key_metrics"], "source": "tests_audit_fixes.py"},
    {"capability": "Artifact identity and unrelated edits", "vector": "Invalid: same source with different artifact package identity. Valid: changed unrelated notes with identical released package.",
     "expectation": "Wrong identity is unsupported until fresh matching evidence; unrelated notes do not invalidate support.",
     "tests": ["test_wrong_artifact_requires_identity_matching_evidence", "test_unrelated_change_preserves_applicability"], "source": "expansion/tests.py"},
    {"capability": "Check authorization and observation limits", "vector": "Invalid check attempt under revoked check permission; valid software functional observation with unobservable required physical scope.",
     "expectation": "Revoked checks never dispatch a subprocess. A software pass does not prove physical fit; release is blocked and technical state remains unknown.",
     "tests": ["test_check_revocation_prevents_actual_subprocess", "test_software_cannot_observe_physical_criterion"], "source": "expansion/tests.py"},
    {"capability": "Shared gate and hidden shadow decisions", "vector": "All fixture families and arms receive identical shadow gate decisions; enforcement applies only to G/P.",
     "expectation": "G/P commits equal gate allowance; other arms commit regardless of hidden shadow result; no false claim that shadow computation is enforcement.",
     "tests": ["test_shadow_gate_same_g_p_and_hidden_outside", "test_all_initial_assessments_and_shared_gate"], "source": "expansion/tests.py"},
    {"capability": "Boundary and deadline guards", "vector": "Invalid paths, arbitrary operations and code injection; exhausted operation budget; expired deadline at dispatch or immediately before commit.",
     "expectation": "Invalid operations return errors; budget and deadline guards prevent the prohibited commit. The late-deadline pilot case retains attempt/gate but no commit.",
     "tests": ["test_no_paths_code_or_evidence_injection", "test_tool_cap", "test_deadline_before_dispatch_has_no_release_side_effect", "test_deadline_rechecked_before_commit"], "source": "tests.py; tests_audit_fixes.py"},
    {"capability": "Partial usage parsing and aggregation", "vector": "Valid explicit deltas sum; absent or partial deltas and missing observations remain unknown rather than zero.",
     "expectation": "Known input counts survive partial records, unknown components and derived totals stay null; a missing delta invalidates totals. Observed-only sums are labeled separately.",
     "tests": ["test_missing_partial_usage_is_null_and_propagates", "test_partial_usage_does_not_become_total_zero_in_scorer", "test_partial_telemetry_null_propagation"], "source": "tests_audit_fixes.py; expansion/tests.py"},
    {"capability": "Finite fixture baseline and independent implementation wiring", "vector": "Frozen fixture-manifest hashes, initial technical labels for every expansion fixture, and oracle/evaluator imports.",
     "expectation": "Manifest digests match; all specified initial labels match; oracle and evaluator do not import the gate, harness or checker. This is code-path separation, not independent-team validation.",
     "tests": ["test_forty_genuine_fixture_cases", "test_all_initial_assessments_and_shared_gate", "test_oracle_has_no_gate_import_and_historical_deps_are_frozen"], "source": "expansion/tests.py"}
]

LIMITS = [
    "The cases are authored, deterministic diagnostic vectors, not participant sessions, random project samples, a population sensitivity/specificity estimate, or an independent-team validation.",
    "Expected classifications are literal contract-based values specified before this local execution. They are not retrospective preregistration of the empirical study and are not generated by the oracle or gate under test.",
    "The semantic oracle covers the narrow integer component, its allowed AST and finite probe inputs. Arbitrary software, concurrency, distributed delivery, production deployment, hostile filesystem access, cryptographic log authenticity and exhaustive malformed-input fuzzing are not established.",
    "The wrong-check-label vector directly constructs a malformed context unavailable through the current allowlisted checker. A failed gate assertion demonstrates a bounded admission-validation gap, not an observed participant exploit or an empirical unsupported release.",
    "A deliberately injected gate rejection tests the false-rejection counter, not the natural incidence of gate errors. A synthetic sink overwrite tests detection after tampering, not operating-system immutability against privileged attackers.",
    "Historical immutability checks compare local bytes with retained local manifests and a before/after inventory. They do not authenticate original acquisition, prove external custody, or make an archive publicly retrievable.",
    "Only the listed existing test suites and focused measurement vectors are run. The post-hoc action-path analysis is not independently validated here; clean full-study regeneration and publication/access dependencies remain separate tasks.",
    "Transport testing uses the existing explicitly fake Python client and local stdio server. No hosted participant client, model response, billing accuracy, sampling behavior or retry distribution is tested.",
    "No physical observation is made. Free-text reasoning and causal effects of handoffs or inspection are not classified. Timing fields in raw logs vary; deterministic claims concern input vectors and classifications, not wall-clock byte identity.",
    "The protected inventory covers regular files under experiments except this new directory, virtual environments and bytecode caches; symlinks are not followed. The runner does not write manuscripts, state files or the knowledge graph. Graph refresh was deliberately omitted because writes outside measurement-validation were forbidden."
]


def markdown(result):
    lines = ["# Reproducible measurement-validation matrix", "",
             "## Scope and reproduction", "",
             "This package addresses priority 3 (Validate measurement) in the round-2 meta-review's five priorities. It does not resolve the separate section 3 interpretation-of-the-ceiling issue, the contribution question, artifact access, or submission readiness. No empirical experiment was rerun or modified.", "",
             "Run from any working directory with the existing environment:", "", "```sh",
             f"PYTHONDONTWRITEBYTECODE=1 {EXPERIMENTS}/.venv/bin/python -B {HERE}/run_validation.py", "```", "",
             "Only Python's standard library is used. Each execution creates a new numbered run directory. No provider CLI or participant model is invoked. Local checker subprocesses execute the actual component tests; the existing fake transport test remains explicitly synthetic.", "",
             "The runner reuses the unchanged pilot, audit-fix and expansion test modules. It redirects their temporary directories into this package, disables bytecode writing, and changes only expansion evaluator path rendering in memory so new logs may remain outside historical workspaces. Tests run in separate processes to avoid pilot/expansion import collisions. Expected focal classifications are stored in cases.json before execution and compared literally with the observed values.", "",
             "The test workers block socket connections and only permit inspected Python checker/server/fake-client subprocess entry points. These are safeguards for this run, not a general security sandbox. The original checker and experiment sources are read in place and never rewritten.", "",
             "## Recorded execution", "",
             f"- Run: `{result['run_directory']}`.",
             f"- Interpreter: `{result['python']}` ({result['python_version']}).",
             f"- Unit tests: {result['tests_run']}; failures: {result['failures']}; errors: {result['errors']}; skipped: {result['skipped']}.",
             f"- Focal matrix vectors recorded: {len(result['observations'])}; matching expectations: {sum(r['matches_expectation'] for r in result['observations'])}.",
             f"- Protected experiment files compared: {result['integrity']['files_before']}; changed: {len(result['integrity']['changed'])}; added outside validation: {len(result['integrity']['added'])}; removed: {len(result['integrity']['removed'])}.",
             f"- Overall validation success: `{str(result['successful']).lower()}`. Nonzero exit status is intentional when any expectation fails; known defects are not converted to expected failures.", "",
             "Uncompressed worker stdout, stderr, individual test outcomes, full scripted event/score files, before/after hashes and this run's combined JSON are retained under the run directory. No synthetic score is written to the empirical results directory or pooled with empirical sessions.", "",
             "## Focal vectors", "",
             "Each expected object is fixed in cases.json independently of the actual implementation output. Independent specification here means a literal contract-derived expectation, not an independent author or external team. Boolean and null values below are JSON values.", "",
             "| Capability and case | Valid/invalid vector | Predefined expectation | Observed classification | Test and retained files | Match |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in result["observations"]:
        fields = [row["capability"] + " / " + row["id"], row["vector"],
                  "`" + json.dumps(row["expected"], sort_keys=True) + "`",
                  "`" + json.dumps(row["observed"], sort_keys=True) + "`",
                  "`focused_tests.py::" + row["test"] + "`; `" + str(row["retained_case"]) + "`",
                  "PASS" if row["matches_expectation"] else "FAIL"]
        lines.append("| " + " | ".join(f.replace("|", "\\|").replace("\n", " ") for f in fields) + " |")
    lines.extend(["", "## Reused validation vectors", "",
                  "These rows refer to assertions in unchanged existing test files. The observed column reports the actual named-test outcome, not inferred values copied from the assertion source. Full test identifiers and any exception are retained in test-results.json and stdout.txt.", "",
                  "| Capability | Valid/invalid vector | Predefined expectation from existing assertions | Observed test outcomes | Existing file/test |",
                  "| --- | --- | --- | --- | --- |"])
    for row in result["reused_matrix"]:
        fields = [row["capability"], row["vector"], row["expectation"],
                  "; ".join(name + "=" + status for name, status in row["observed"].items()),
                  row["source"] + ": " + ", ".join(row["tests"])]
        lines.append("| " + " | ".join(f.replace("|", "\\|") for f in fields) + " |")
    lines.extend(["", "## Failures and untested scope", ""])
    for record in result["test_records"]:
        if record["status"] in {"FAIL", "ERROR"}:
            lines.append(f"- **{record['status']}** `{record['test']}`. See the exact traceback in `{result['run_directory']}` and observed/expected focal fields above. No historical implementation was fixed by this task.")
    lines.extend("- " + limitation for limitation in LIMITS)
    lines.extend(["", "The matrix is evidence for the measured classification behavior only. A complete mapping does not make failed assertions pass and does not automatically close editorial review or authorize promotion.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=["pilot", "expansion", "focused"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.worker:
        output = args.output.resolve()
        if HERE not in output.parents:
            parser.error("Worker output must be inside measurement-validation")
        return worker(args.worker, output)
    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    index = 1
    while (runs / f"run-{index:03d}").exists():
        index += 1
    run = runs / f"run-{index:03d}"
    run.mkdir()
    before = protected_hashes()
    save(run / "protected-before.json", before)
    source_hashes = {name: sha(HERE / name) for name in ["run_validation.py", "focused_tests.py", "cases.json"]}
    save(run / "validation-source-hashes.json", source_hashes)
    groups, records, commands = [], [], []
    for group in ["pilot", "expansion", "focused"]:
        output = run / group
        output.mkdir()
        command = [sys.executable, "-B", str(HERE / "run_validation.py"), "--worker", group, "--output", str(output)]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "TMPDIR": str(output)}
        completed = subprocess.run(command, cwd=HERE, env=env, capture_output=True, text=True, timeout=180)
        (output / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (output / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
        commands.append({"command": command, "returncode": completed.returncode, "cwd": str(HERE),
                         "environment_overrides": {k: env[k] for k in ["PYTHONDONTWRITEBYTECODE", "PYTHONHASHSEED", "TMPDIR"]}})
        path = output / "test-results.json"
        if path.exists():
            data = json.loads(path.read_text())
            groups.append(data)
            records.extend(data["records"])
        else:
            records.append({"test": group + ".worker", "status": "ERROR", "traceback": completed.stderr})
        print(f"{group}: exit={completed.returncode}; full stdout retained in {output / 'stdout.txt'}")
    after = protected_hashes()
    save(run / "protected-after.json", after)
    integrity = {"files_before": len(before), "files_after": len(after),
                 "changed": [name for name in before.keys() & after.keys() if before[name] != after[name]],
                 "added": sorted(after.keys() - before.keys()), "removed": sorted(before.keys() - after.keys())}
    observation_path = run / "focused" / "observations.json"
    observations = json.loads(observation_path.read_text()) if observation_path.exists() else []
    specs = json.loads((HERE / "cases.json").read_text())["cases"]
    missing = sorted({c["id"] for c in specs} - {c["id"] for c in observations})
    statuses = {r["test"].split(".")[-1]: r["status"] for r in records}
    reused = [{**row, "observed": {name: statuses.get(name, "NOT RUN") for name in row["tests"]}} for row in SUPPLEMENTAL]
    successful = (all(c["returncode"] == 0 for c in commands) and not missing and
                  all(r["matches_expectation"] for r in observations) and
                  not any(integrity[k] for k in ["changed", "added", "removed"]))
    result = {"schema_version": 1, "data_kind": "scripted_measurement_validation_not_empirical_sessions",
              "run_directory": str(run.relative_to(HERE)), "python": sys.executable,
              "python_version": platform.python_version(), "platform": platform.platform(),
              "participant_model_calls": 0, "successful": successful, "commands": commands,
              "source_hashes": source_hashes, "integrity": integrity,
              "tests_run": sum(g["tests_run"] for g in groups),
              "failures": sum(r["status"] == "FAIL" for r in records),
              "errors": sum(r["status"] == "ERROR" for r in records),
              "skipped": sum(r["status"] == "SKIP" for r in records),
              "test_records": records, "observations": observations, "missing_vectors": missing,
              "reused_matrix": reused, "limits": LIMITS}
    save(run / "validation-results.json", result)
    save(HERE / "validation-results.json", result)
    (HERE / "validation-matrix.md").write_text(markdown(result), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ["successful", "tests_run", "failures", "errors", "skipped", "missing_vectors", "integrity"]}, indent=2))
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
