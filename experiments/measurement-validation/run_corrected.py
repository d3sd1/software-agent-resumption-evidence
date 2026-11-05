#!/usr/bin/env python3
"""Post-study gate variant validation and read-only empirical decision comparison."""
import argparse
import copy
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import unittest
from collections import Counter

HERE = Path(__file__).resolve().parent
EXPERIMENTS = HERE.parent
EXPANSION = EXPERIMENTS / "expansion"
sys.dont_write_bytecode = True


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BASE = load("validation_round_one_runner", HERE / "run_validation.py")
FIXED = load("controls_corrected", HERE / "controls_corrected.py")
ORIGINAL = load("controls_original_for_comparison", EXPANSION / "controls.py")
PILOT = load("pilot_controls_original_for_comparison", EXPERIMENTS / "controls.py")
SAVE = BASE.save


def sha(data):
    return hashlib.sha256(data).hexdigest()


def no_timing(value):
    if isinstance(value, dict):
        return {k: no_timing(v) for k, v in value.items() if k != "runtime_seconds"}
    if isinstance(value, list):
        return [no_timing(v) for v in value]
    return value


def context_from_fixture(fixture):
    package = fixture["package"]
    payload = json.dumps(package, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return {"package": package, "candidate_sha256": sha(payload), "contract": fixture["contract"],
            "dependencies": fixture["dependencies"], "policy": fixture["policy"], "evidence": fixture["evidence"]}


def contract_worker(output):
    manifest = json.loads((EXPANSION / "fixture-manifest.json").read_text())
    case = next(c for c in manifest["cases"] if c["family"] == "unrelated-change-valid" and c["fixture_order_seed"] == 42)
    fixture = json.loads((EXPANSION / "fixtures" / case["case_id"] / "fixture.json").read_text())
    initial = context_from_fixture(fixture)
    specs = json.loads((HERE / "cases-corrected.json").read_text())["cases"]
    observations = []

    def set_labels(record, check, scope):
        record["check"], record["scope"] = check, scope
        raw = json.loads(record["raw"]["stdout"])
        raw["check"], raw["scope"] = check, scope
        record["raw"]["stdout"] = json.dumps(raw)
        record["raw"]["parsed"] = copy.deepcopy(raw)
        command = record["raw"]["command_template"]
        command[command.index("--check") + 1] = check

    def fail_record(record):
        record["outcome"] = "fail"
        record["raw"]["exit_code"] = 1
        raw = json.loads(record["raw"]["stdout"])
        raw["outcome"] = "fail"
        record["raw"]["stdout"] = json.dumps(raw)
        record["raw"]["parsed"] = copy.deepcopy(raw)
        return record

    def build(identifier):
        context = copy.deepcopy(initial)
        record = context["evidence"][0]
        if identifier in {"valid-compile-contract", "compile-insufficient"}:
            set_labels(record, "compile", "compile")
            if identifier == "valid-compile-contract":
                context["contract"]["required_scopes"] = ["compile"]
        elif identifier == "compile-labeled-functional-scope":
            set_labels(record, "compile", "real-local-functional-v2")
        elif identifier == "functional-labeled-compile-scope":
            set_labels(record, "functional", "compile")
            context["contract"]["required_scopes"] = ["compile"]
        elif identifier == "unknown-check":
            set_labels(record, "invented-check", "real-local-functional-v2")
        elif identifier == "missing-check":
            del record["check"]
        elif identifier == "nonstring-check":
            record["check"] = ["functional"]
        elif identifier in {"unknown-scope", "fabricated-physical-scope"}:
            scope = "invented-scope" if identifier == "unknown-scope" else "physical-fit"
            set_labels(record, "functional", scope)
            context["contract"]["required_scopes"] = [scope]
        elif identifier == "stdout-label-mismatch":
            raw = json.loads(record["raw"]["stdout"])
            raw["check"] = "compile"
            record["raw"]["stdout"] = json.dumps(raw)
        elif identifier == "cached-label-mismatch":
            record["raw"]["parsed"]["check"] = "compile"
        elif identifier == "command-label-mismatch":
            command = record["raw"]["command_template"]
            command[command.index("--check") + 1] = "compile"
        elif identifier == "missing-command-provenance":
            del record["raw"]["command_template"]
        elif identifier == "duplicate-command-check":
            record["raw"]["command_template"] += ["--check", "functional"]
        elif identifier == "command-check-without-value":
            record["raw"]["command_template"] = ["checker.py", "--check"]
        elif identifier == "valid-functional-failure":
            fail_record(record)
        elif identifier == "invalid-plus-valid":
            invalid = copy.deepcopy(record)
            invalid["id"] = "invalid-compile-label"
            set_labels(invalid, "compile", "real-local-functional-v2")
            context["evidence"].append(invalid)
        elif identifier == "valid-pass-and-fail":
            failure = fail_record(copy.deepcopy(record))
            failure["id"] = "valid-functional-failure"
            context["evidence"].append(failure)
        elif identifier == "valid-no-cached-parsed":
            del record["raw"]["parsed"]
        elif identifier != "valid-functional":
            raise ValueError(identifier)
        return context

    class ContractTests(unittest.TestCase):
        pass

    def make_test(spec):
        def test(self):
            context = build(spec["id"])
            original, corrected = ORIGINAL.gate(context), FIXED.gate(context)
            observed = {"technical_state": corrected["technical"]["technical_state"], "allowed": corrected["allowed"]}
            observation = {**spec, "original": no_timing(original), "corrected": no_timing(corrected),
                           "observed": observed, "matches_expectation": observed == spec["expected"],
                           "label_errors": [FIXED.label_provenance_error(e) for e in context["evidence"]],
                           "test": self.id()}
            observations.append(observation)
            SAVE(output / (spec["id"] + "-context.json"), context)
            self.assertEqual(observed, spec["expected"])
        return test
    for spec in specs:
        setattr(ContractTests, "test_" + spec["id"].replace("-", "_"), make_test(spec))
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2, resultclass=BASE.RecordedResult).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ContractTests))
    SAVE(output / "test-results.json", {"group": "contract", "tests_run": result.testsRun,
         "successful": result.wasSuccessful(), "records": result.records})
    SAVE(output / "observations.json", observations)
    return 0 if result.wasSuccessful() else 1


def evidence_objects(node, pointer=""):
    if isinstance(node, dict):
        for key, value in node.items():
            location = pointer + "/" + key
            if key == "evidence":
                if isinstance(value, list):
                    for i, record in enumerate(value):
                        yield location + "/" + str(i), record
                elif isinstance(value, dict):
                    yield location, value
            else:
                yield from evidence_objects(value, location)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from evidence_objects(value, pointer + "/" + str(i))


def pilot_label_error(record):
    # Explicit schema adapter for auditing pilot labels, not an expansion-gate deployment.
    if not isinstance(record, dict):
        return "record_not_object"
    mappings = {"functional-real": ("real-local-functional", "functional", "real-local-functional-v2"),
                "functional-mock": ("mock-functional", "compile", "compile")}
    check = record.get("check")
    if not isinstance(check, str) or check not in mappings:
        return "unknown_or_missing_check"
    scope, translated_check, translated_scope = mappings[check]
    if record.get("scope") != scope:
        return "check_scope_mismatch"
    # Validate the pilot's own labels before translating only the expected vocabulary.
    item = copy.deepcopy(record)
    item["check"], item["scope"] = translated_check, translated_scope
    raw = item.get("raw")
    if not isinstance(raw, dict):
        return "missing_raw_provenance"
    try:
        stdout = json.loads(raw["stdout"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return "unreadable_stdout"
    if not isinstance(stdout, dict) or stdout.get("check") != check or stdout.get("scope") != scope:
        return "stdout_label_mismatch"
    stdout["check"], stdout["scope"] = translated_check, translated_scope
    raw["stdout"] = json.dumps(stdout)
    if "parsed" in raw:
        parsed = raw["parsed"]
        if not isinstance(parsed, dict) or parsed.get("check") != check or parsed.get("scope") != scope:
            return "cached_label_mismatch"
        parsed["check"], parsed["scope"] = translated_check, translated_scope
    command = raw.get("command_template")
    if not isinstance(command, list) or command.count("--check") != 1:
        return "ambiguous_or_missing_command_check"
    index = command.index("--check")
    if index + 1 >= len(command) or command[index + 1] != check:
        return "command_check_mismatch"
    command[index + 1] = translated_check
    return FIXED.label_provenance_error(item)


def empirical_audit(output):
    # Retained per-run lists define the complete empirical frame. Scripted reference runs are excluded.
    baseline = json.loads((HERE / "runs" / "run-001" / "protected-before.json").read_text())
    read_hashes, changed_inputs = {}, []
    records, contexts, phases = {}, [], {}
    stored_gate_mismatches = []
    unlaunched_or_missing = []

    def read(path, jsonl=False):
        data = path.read_bytes()
        relative = str(path.relative_to(EXPERIMENTS))
        digest = sha(data)
        read_hashes[relative] = digest
        if baseline.get(relative) != digest:
            changed_inputs.append(relative)
        return [json.loads(line) for line in data.splitlines() if line.strip()] if jsonl else json.loads(data)

    def labels(phase, path, node):
        for pointer, record in evidence_objects(node):
            digest = sha(json.dumps(record, sort_keys=True, separators=(",", ":")).encode())
            key = phase + ":" + digest
            error = FIXED.label_provenance_error(record) if phase == "expansion" else pilot_label_error(record)
            incomplete = phase == "expansion" and (not isinstance(record, dict) or record.get("complete") is not True)
            status = "incomplete_record" if incomplete else "valid_labels" if error is None else "invalid_complete_labels"
            if key not in records:
                records[key] = {"phase": phase, "record_sha256": digest, "status": status, "label_error": error,
                                "check": record.get("check") if isinstance(record, dict) else None,
                                "scope": record.get("scope") if isinstance(record, dict) else None, "locations": []}
            records[key]["locations"].append(str(path.relative_to(EXPERIMENTS)) + "#" + pointer)

    def compare(phase, run_id, location, context):
        if phase == "expansion":
            old, new = ORIGINAL.gate(context), FIXED.gate(context)
            mode = "actual_original_vs_separate_corrected_expansion_variant"
        else:
            def gate(evidence):
                return PILOT.gate(context["candidate_sha256"], context["contract"], context["dependencies"], evidence, context["policy"])
            old = gate(context["evidence"])
            new = gate([e for e in context["evidence"] if pilot_label_error(e) is None])
            mode = "pilot_original_vs_analogous_label_filter_sensitivity_check_not_expansion_variant"
        old, new = no_timing(old), no_timing(new)
        contexts.append({"phase": phase, "run_id": run_id, "location": location, "comparison": mode,
                         "context_sha256": sha(json.dumps(context, sort_keys=True).encode()),
                         "original": old, "corrected_or_filtered": new,
                         "decision_changed": old["allowed"] != new["allowed"],
                         "technical_state_changed": old["technical"]["technical_state"] != new["technical"]["technical_state"],
                         "classification_changed_excluding_runtime": old != new})
        return old

    for phase, result_file in [("pilot", "pilot_results.json"), ("expansion", "expanded_results.json")]:
        data = read(EXPERIMENTS / "results" / result_file)
        rows = data["per_run"]
        ids = [row["id"] if phase == "pilot" else row["opaque_id"] for row in rows]
        if len(ids) != len(set(ids)):
            raise AssertionError("Duplicate empirical run identifiers")
        phases[phase] = {"runs_in_retained_frame": len(rows), "runs_audited": 0, "canonical_state_evidence_occurrences": 0}
        for row, run_id in zip(rows, ids):
            folder = EXPERIMENTS / "runs" / run_id if phase == "pilot" else EXPANSION / "workspaces" / run_id
            if not row.get("launched") or not (folder / "state.json").exists():
                unlaunched_or_missing.append({"phase": phase, "run_id": run_id})
                continue
            state_path = folder / "state.json"
            state = read(state_path)
            labels(phase, state_path, state)
            phases[phase]["runs_audited"] += 1
            phases[phase]["canonical_state_evidence_occurrences"] += len(state["evidence"])
            if phase == "expansion":
                compare(phase, run_id, str(state_path.relative_to(EXPERIMENTS)) + "#/fixture", context_from_fixture(state["fixture"]))
                compare(phase, run_id, str(state_path.relative_to(EXPERIMENTS)) + "#/final_context", state["final_context"])
            events_path = folder / "release-events.jsonl"
            if events_path.exists():
                events = read(events_path, jsonl=True)
                labels(phase, events_path, events)
                attempts = {}
                for index, event in enumerate(events):
                    if event["type"] in {"attempt", "commit"}:
                        old = compare(phase, run_id, str(events_path.relative_to(EXPERIMENTS)) + "#/" + str(index), event["context"])
                        if event["type"] == "attempt":
                            attempts[event["index"]] = old
                    elif event["type"] == "gate":
                        recorded = no_timing(event["decision"])
                        recomputed = attempts.get(event["index"])
                        if recorded != recomputed:
                            stored_gate_mismatches.append({"phase": phase, "run_id": run_id, "event_index": index,
                                                           "recorded": recorded, "recomputed_original": recomputed})
            tool_path = folder / "tool-events.jsonl"
            if tool_path.exists():
                labels(phase, tool_path, read(tool_path, jsonl=True))
    record_rows = list(records.values())
    for phase, details in phases.items():
        selected = [r for r in record_rows if r["phase"] == phase]
        decisions = [r for r in contexts if r["phase"] == phase]
        details.update(unique_record_digests=len(selected), label_status_counts=dict(Counter(r["status"] for r in selected)),
                       label_error_counts=dict(Counter(r["label_error"] for r in selected if r["label_error"])),
                       decision_contexts=len(decisions), decision_changes=sum(r["decision_changed"] for r in decisions),
                       technical_state_changes=sum(r["technical_state_changed"] for r in decisions),
                       classification_changes_excluding_runtime=sum(r["classification_changed_excluding_runtime"] for r in decisions))
    audit = {"scope": "All retained pilot and expansion per_run entries; state evidence, trusted tool-event evidence and release-event contexts. Expansion initial/final contexts are also compared. No provider narrative, deterministic reference, failed preflight or new scripted case is treated as empirical data.",
             "counting": "Evidence records are deduplicated by canonical JSON digest within phase; location lists preserve all inspected repetitions. Counts are records/contexts, not independent observations.",
             "pilot_comparison_limit": "Expansion controls do not accept pilot schema. Pilot labels are checked against pilot checker names; analogous evidence filtering is evaluated with the original pilot gate. This is not deployment of the expansion variant.",
             "phases": phases, "all_complete_record_labels_valid": not any(r["status"] == "invalid_complete_labels" for r in record_rows),
             "all_records_fully_valid": all(r["status"] == "valid_labels" for r in record_rows),
             "unlaunched_or_missing": unlaunched_or_missing, "changed_inputs_since_run001": sorted(set(changed_inputs)),
             "stored_gate_mismatches": stored_gate_mismatches, "input_hashes": read_hashes,
             "evidence_records": record_rows, "contexts": contexts}
    audit["successful"] = (audit["all_complete_record_labels_valid"] and not unlaunched_or_missing and not changed_inputs and
                           not stored_gate_mismatches and not any(r["classification_changed_excluding_runtime"] for r in contexts))
    SAVE(output / "empirical-audit.json", audit)
    print(json.dumps({k: audit[k] for k in ["phases", "all_complete_record_labels_valid", "all_records_fully_valid", "successful"]}, indent=2))
    return audit


def protected_state():
    paths = list((HERE / "runs" / "run-001").rglob("*"))
    paths += [HERE / name for name in ["cases.json", "focused_tests.py", "run_validation.py", "validation-matrix.md", "validation-results.json", "hygiene.json"]]
    paths += [EXPANSION / name for name in ["controls.py", "oracle.py", "checker.py", "domain.py", "tests.py", "harness.py", "config-v2.json"]]
    paths += [EXPERIMENTS / name for name in ["controls.py", "tests.py", "tests_audit_fixes.py"]]
    # Only targeted protection hashes are reread; the corpus audit reads each selected input once.
    return {str(p.relative_to(EXPERIMENTS)): sha(p.read_bytes()) for p in paths if p.is_file()}


def report(result):
    lines = ["# Corrected measurement-validation variant", "",
             "## Status and provenance", "",
             "This is a post-study corrective validation round. The original study used the original controls, not this variant. The original matrix, expectations, run-001, historical implementation and frozen artifacts remain unchanged. The corrected implementation exists only in measurement-validation/controls_corrected.py.", "",
             "The patch admits only the checker-defined pairs compile/compile and functional/real-local-functional-v2. Record and stdout labels must agree; any cached parsed labels must agree too. Complete capture-format records must identify exactly one matching --check value in command_template. No local check can establish physical-fit. This is provenance consistency, not cryptographic authenticity. Missing command provenance is an explicitly stricter post-study capture-format requirement.", "",
             "Existing classification, staleness, conflict precedence and permission logic are otherwise unchanged. Inadmissible records are excluded; they do not erase an independent valid pass. The new test vectors include both directions of the check/scope mismatch, invented labels/scopes, missing and ambiguous provenance, valid passes/failures, a compile-only contract, and contradictory valid observations.", "",
             f"Original controls SHA-256: `{result['provenance']['original_sha256']}`.",
             f"Variant SHA-256: `{result['provenance']['variant_sha256']}`.",
             f"Exact diff and source identities: `{result['run_directory']}/patch-provenance.json` and `controls.patch`.", "",
             "## Reproduce", "", "```sh",
             f"PYTHONDONTWRITEBYTECODE=1 {EXPERIMENTS}/.venv/bin/python -B {HERE}/run_corrected.py", "```", "",
             "The runner creates a new numbered directory after run-001; this execution is run-002. The existing suites are reused without editing their source. Only expansion/focused workers load the separate variant as their in-memory controls module; pilot tests retain original pilot controls. No participant client runs. The original runner's temporary-directory redirection and subprocess allowlist still apply. Raw stdout/stderr and all scripted vectors remain separate from empirical data.", "",
             "## Executed tests", "",
             f"Tests: {result['tests_run']}; failures: {result['failures']}; errors: {result['errors']}; skipped: {result['skipped']}. Overall success: `{str(result['successful']).lower()}`.",
             "The failure in run-001 is preserved. Its unchanged expectation is tested again using the variant; the following table shows original versus corrected observations, rather than replacing the original outcome.", "",
             "| Original focal vector | Original observation | Corrected observation | Unchanged expectation | Corrected match |",
             "| --- | --- | --- | --- | --- |"]
    for row in result["focal_comparison"]:
        lines.append("| " + " | ".join([row["id"], "`" + json.dumps(row["original_observed"], sort_keys=True) + "`",
                     "`" + json.dumps(row["corrected_observed"], sort_keys=True) + "`",
                     "`" + json.dumps(row["expected"], sort_keys=True) + "`", str(row["matches_expectation"])]) + " |")
    lines.extend(["", "## Additional contract vectors", "",
                  "| Vector | Predefined corrected expectation | Observed original | Observed corrected | Match |",
                  "| --- | --- | --- | --- | --- |"])
    for row in result["contract_observations"]:
        old = {"technical_state": row["original"]["technical"]["technical_state"], "allowed": row["original"]["allowed"]}
        lines.append("| " + " | ".join([row["id"] + ": " + row["description"], "`" + json.dumps(row["expected"]) + "`",
                     "`" + json.dumps(old) + "`", "`" + json.dumps(row["observed"]) + "`", str(row["matches_expectation"])]) + " |")
    audit = result["empirical_summary"]
    lines.extend(["", "## Read-only empirical input audit", "", audit["scope"], "", audit["counting"], "", audit["pilot_comparison_limit"], "",
                  "The audit records source paths, JSON pointers, record/context hashes, original classifications, corrected classifications and every exception. It uses captured dependencies, not current checker identity, when replaying historical gate inputs. This is deterministic offline reassessment, not rerunning participants or replacing historical results.", "",
                  "```json", json.dumps(audit["phases"], indent=2), "```", "",
                  f"All complete record labels valid: `{str(audit['all_complete_record_labels_valid']).lower()}`. All records fully valid, including intentionally missing/torn evidence: `{str(audit['all_records_fully_valid']).lower()}`.",
                  "Incomplete fixture evidence is reported separately and is not silently called valid. A zero decision-change count applies only to the enumerated retained contexts, not unseen inputs or population safety.", "",
                  f"Stored gate mismatches against original re-evaluation: {audit['stored_gate_mismatches_count']}. Inputs differing from run-001 hashes: {audit['changed_inputs_count']}. Missing/unlaunched empirical entries: {audit['unlaunched_or_missing_count']}.",
                  f"Preserved run-001/original-file changes: {len(result['preservation_changes'])}. Any real discrepancy, failed test, changed captured gate classification or missing required input makes this runner exit nonzero.", "",
                  "## Limits", "",
                  "This validates finite authored cases and enumerated historical records only. It is not validation by an independent team, a prevalence/sensitivity estimate, a causal study, a proof against arbitrary log forgery, or public artifact release. The semantic oracle remains narrow and unchanged; the patch does not repair every possible malformed schema or add physical observation. Pilot filtering is a schema-specific sensitivity check, not a claim that the expansion variant was applied to pilot execution. Timing measurements are excluded from deterministic decision comparisons.", "",
                  "No historical source, fixture, result, frozen snapshot, manuscript or pipeline status was changed. The original failure remains documented; the variant was never active in the completed empirical study. Any production adoption would require a separately authorized change.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=["pilot", "expansion", "focused", "contract"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.worker:
        output = args.output.resolve()
        if HERE not in output.parents:
            parser.error("Output must stay under measurement-validation")
        if args.worker == "contract":
            return contract_worker(output)
        if args.worker != "pilot":
            sys.modules["controls"] = FIXED
        return BASE.worker(args.worker, output)
    index = 2
    while (HERE / "runs" / f"run-{index:03d}").exists():
        index += 1
    run = HERE / "runs" / f"run-{index:03d}"
    run.mkdir()
    before = protected_state()
    SAVE(run / "preserved-before.json", before)
    original_path, variant_path = EXPANSION / "controls.py", HERE / "controls_corrected.py"
    original, variant = original_path.read_bytes(), variant_path.read_bytes()
    provenance = {"original_path": str(original_path), "original_sha256": sha(original), "variant_path": str(variant_path),
                  "variant_sha256": sha(variant), "historical_implementation_changed": False,
                  "variant_active_in_original_study": False,
                  "contract_source_hashes": {name: sha((EXPANSION / name).read_bytes()) for name in ["checker.py", "domain.py", "config-v2.json"]},
                  "validation_source_hashes": {name: sha((HERE / name).read_bytes()) for name in ["run_corrected.py", "cases-corrected.json", "cases.json", "focused_tests.py", "run_validation.py"]}}
    SAVE(run / "patch-provenance.json", provenance)
    (run / "controls.patch").write_text("".join(difflib.unified_diff(original.decode().splitlines(True), variant.decode().splitlines(True),
                                            fromfile="historical/expansion/controls.py", tofile="post-study/measurement-validation/controls_corrected.py")))
    records, commands, groups = [], [], []
    for group in ["pilot", "expansion", "focused", "contract"]:
        output = run / group
        output.mkdir()
        command = [sys.executable, "-B", str(HERE / "run_corrected.py"), "--worker", group, "--output", str(output)]
        completed = subprocess.run(command, cwd=HERE, capture_output=True, text=True, timeout=180,
                                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "TMPDIR": str(output)})
        (output / "stdout.txt").write_text(completed.stdout)
        (output / "stderr.txt").write_text(completed.stderr)
        commands.append({"command": command, "returncode": completed.returncode})
        result_file = output / "test-results.json"
        if result_file.exists():
            group_result = json.loads(result_file.read_text())
            records.extend(group_result["records"])
            groups.append(group_result)
        else:
            records.append({"test": group + ".worker", "status": "ERROR", "traceback": completed.stderr})
        print(f"{group}: exit={completed.returncode}; stdout={output / 'stdout.txt'}")
    audit = empirical_audit(run)
    after = protected_state()
    SAVE(run / "preserved-after.json", after)
    preservation_changes = [name for name in before.keys() | after.keys() if before.get(name) != after.get(name)]
    old_rows = {r["id"]: r for r in json.loads((HERE / "runs" / "run-001" / "focused" / "observations.json").read_text())}
    new_path = run / "focused" / "observations.json"
    new_rows = json.loads(new_path.read_text()) if new_path.exists() else []
    comparisons = [{"id": r["id"], "expected": old_rows[r["id"]]["expected"], "original_observed": old_rows[r["id"]]["observed"],
                    "corrected_observed": r["observed"], "matches_expectation": r["observed"] == old_rows[r["id"]]["expected"]} for r in new_rows]
    contract_path = run / "contract" / "observations.json"
    contract = json.loads(contract_path.read_text()) if contract_path.exists() else []
    expected_contract = json.loads((HERE / "cases-corrected.json").read_text())["cases"]
    complete_vectors = len(comparisons) == len(old_rows) and len(contract) == len(expected_contract)
    successful = (all(c["returncode"] == 0 for c in commands) and audit["successful"] and not preservation_changes and complete_vectors and
                  all(r["matches_expectation"] for r in comparisons + contract))
    result = {"run_directory": str(run.relative_to(HERE)), "data_kind": "post_study_corrective_validation_not_participant_sessions",
              "successful": successful, "python": sys.executable, "python_version": platform.python_version(), "participant_model_calls": 0,
              "provenance": provenance, "commands": commands, "tests_run": sum(g["tests_run"] for g in groups),
              "failures": sum(r["status"] == "FAIL" for r in records), "errors": sum(r["status"] == "ERROR" for r in records),
              "skipped": sum(r["status"] == "SKIP" for r in records), "test_records": records,
              "preservation_changes": preservation_changes, "focal_comparison": comparisons, "contract_observations": contract,
              "empirical_summary": {**{k: audit[k] for k in ["scope", "counting", "pilot_comparison_limit", "phases", "all_complete_record_labels_valid", "all_records_fully_valid", "successful"]},
                                    "stored_gate_mismatches_count": len(audit["stored_gate_mismatches"]),
                                    "changed_inputs_count": len(audit["changed_inputs_since_run001"]),
                                    "unlaunched_or_missing_count": len(audit["unlaunched_or_missing"])}}
    SAVE(run / "corrected-results.json", result)
    SAVE(HERE / "validation-results-corrected.json", result)
    (HERE / "validation-matrix-corrected.md").write_text(report(result), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ["run_directory", "successful", "tests_run", "failures", "errors", "skipped", "preservation_changes"]}, indent=2))
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
