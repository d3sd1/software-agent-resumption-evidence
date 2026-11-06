"""Bounded post-review diagnostics. Run with Python -I -B; no CLI/model/network.

Only copied own instrument code is imported. Public source packages are data;
no upstream program, checker, participant runner, preflight or freezer is invoked.
"""
import argparse
import copy
import csv
import hashlib
import importlib
import importlib.util
import json
import logging
from pathlib import Path
import shutil
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT.parents[1]
MARKER = "Derived current-applicability projection (not an independent check): "


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=True, sort_keys=True)
        stream.write("\n")


def table(path, rows):
    if not rows:
        raise ValueError("Refuse silently empty table")
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with Path(path).open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
                             for key, value in row.items()})


def inventory(path):
    path = Path(path)
    files = [path] if path.is_file() else sorted(path.rglob("*"))
    result = {}
    for file in files:
        if file.is_symlink():
            raise ValueError("Input symlink refused: " + str(file))
        if file.is_file():
            result[str(file.resolve())] = {"sha256": digest(file.read_bytes()), "bytes": file.stat().st_size}
    return result


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compact_projection(value):
    return {k: v for k, v in value.items() if k != "runtime_seconds"}


def exposed_record_valid(record, contract, binding, target):
    """Independent visible-data check for this finite witness, not a new scorer.

    This function receives returned documents only, not a fixture/current state or
    oracle. Its acceptance predictions are NOT used as expected probe outcomes.
    """
    try:
        raw = record["raw"]
        parsed = json.loads(raw["stdout"])
        if (record["complete"] is not True or record["check"] != "functional"
                or record["scope"] != contract["scope"] or record["binding"] != binding
                or binding["criterion"] != contract["criterion"] or record["subject_manifest"] != target
                or record["subject_sha256"] != digest(canonical(target))
                or raw["parsed"] != parsed or raw["timed_out"] is not False):
            return False
        if any(parsed.get(k) != record[k] for k in ("check", "scope", "outcome", "subject_sha256")):
            return False
        cmd = raw["command_template"]
        for flag, value in (("--check", "functional"), ("--case", contract["case"]), ("--subject", record["subject_sha256"])):
            if cmd.count(flag) != 1 or cmd[cmd.index(flag) + 1] != value:
                return False
        result = parsed["adapter_result"]
        passed = record["outcome"] == "pass"
        if record["outcome"] not in ("pass", "fail"):
            return False
        if (result["case"] != contract["case"] or parsed["case"] != contract["case"]
                or result["tests_run"] != contract["tests_run"] or result["skipped"] != []
                or result["success"] is not passed or raw["exit_code"] != (0 if passed else 1)
                or parsed["adapter_returncode"] != raw["exit_code"]):
            return False
        failures = result["failure_count"] + result["error_count"]
        if (passed and failures != 0) or (not passed and failures <= 0):
            return False
        copies = [json.loads(line[12:]) for line in parsed["adapter_stdout"].splitlines() if line.startswith("RESULT_JSON ")]
        return copies == [result]
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def information_policy(initial_prompt, call):
    """Only exposed prompt + tool-result capability; no case/state/arm/fixture access."""
    exposed = {}
    directory = call("list_context", {})
    names = [item["name"] for item in directory["documents"]]
    proof = {"requested_documents": [], "trusted_projection": False,
             "trust": "Frozen tool contracts; initial current projection covers technical inputs only; no out-of-band mutation"}

    def get(name):
        if name not in names:
            raise RuntimeError("Required exposed document is absent")
        if name not in exposed:
            args = {} if directory["regime"] == "bundled" else {"name": name}
            response = call("read_context", args)
            proof["requested_documents"].append("ALL" if not args else name)
            for doc in response["documents"]:
                exposed[doc["name"]] = json.loads(doc["content"])
        return exposed[name]

    contract, workspace = get("contract.json"), get("workspace.json")
    full = dict(workspace["full_manifest"])
    target = {k: v for k, v in full.items() if k.startswith("source/")}
    protected = {k: v for k, v in full.items() if not k.startswith("source/")}
    if contract["release_authorized"] is not True or protected != contract["preserve"]:
        raise RuntimeError("Exposed authorization/protection is insufficient; no release request")
    proof.update(authorization_from_contract=True, protection_from_contract_and_workspace=True)
    projection = json.loads(initial_prompt.split(MARKER, 1)[1]) if MARKER in initial_prompt else None
    if projection is not None and projection["technical"] == "supported":
        proof["trusted_projection"] = True
        proof["technical_basis"] = "Initial trusted current projection; not inferred permission or preservation"
    else:
        history, binding = get("history.json"), get("dependencies.json")
        verified_target = workspace["verified_executable_manifest"]
        admitted = [record for record in history["evidence"] if exposed_record_valid(record, contract, binding, verified_target)]
        if not any(record["outcome"] == "pass" for record in admitted) or any(record["outcome"] == "fail" for record in admitted):
            raise RuntimeError("Visible records do not justify verified-target reuse; no release request")
        if target != verified_target:
            restored = call("restore_verified", {})
            if restored.get("restored") is not True or restored.get("note_preserved") is not True or restored["executable_manifest"] != verified_target:
                raise RuntimeError("Restoration response does not meet visible target/preservation contract")
            full = {**protected, **restored["executable_manifest"]}
        proof["technical_basis"] = "Complete visible historical record/current binding and identity, plus returned restoration manifest when needed"
    released = call("release", {})
    if released.get("allowed") is not True or released.get("technical") != "supported":
        raise RuntimeError("Expected justified release was not allowed")
    if not released["release_id"].endswith(digest(canonical(full))):
        raise RuntimeError("Committed receipt does not bind the exposed full manifest")
    call("finish", {"technical": "supported", "disposition": "delivered", "release_id": released["release_id"],
                    "reason": "Post-review deterministic exposed-information witness, not participant behavior"})
    proof["committed_identity_from_receipt"] = released["release_id"]
    return proof


def final_view(finish, phase):
    if finish is None:
        return {"present": False, "disposition": None, "technical": None}
    return {"present": True,
            "disposition": finish["disposition"] if phase == "C" else {"released": "delivered", "hold": "hold"}[finish["status"]],
            "technical": finish["technical"] if phase == "C" else finish["assessment"]}


def generic_views(finish, phase, requests, commits, final_eligibility, observability):
    final = final_view(finish, phase)
    committed = {"committed_eligibility_sequence": commits}
    full = {"request_eligibility_sequence": requests, **committed, "final": final,
            "current_eligibility": final_eligibility, "observability": observability}
    return {"final_only": final, "commit_only": committed, "full_event": full}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, default=DRAFT / "release-staging/artifact-extended-access-v2-final66")
    parser.add_argument("--controls-receipt", type=Path, default=DRAFT / "experiments/access-study/capsules/cohort-001/local-validation.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT) or out == ROOT:
        raise ValueError("Output must be a NEW directory inside diagnostic-followup")
    out.mkdir(parents=True, exist_ok=False)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(out / "execution.log"), logging.StreamHandler()])
    start = time.monotonic()
    plan, expected, maps = read(ROOT / "plan.json"), read(ROOT / "expectations.json"), read(ROOT / "semantic-map.json")
    write(out / "pre-execution.json", {"started_at_unix": time.time(), "plan_sha256": digest((ROOT / "plan.json").read_bytes()),
                                      "expectations_sha256": digest((ROOT / "expectations.json").read_bytes()),
                                      "script_sha256": digest(Path(__file__).read_bytes()),
                                      "model_calls": 0, "public_controls_rerun": False})
    artifact = args.artifact.resolve()
    exp = artifact / "experiments"
    capsule = exp / "access-study/capsules/cohort-001"
    prepared = capsule / "prepared"
    collection = exp / "access-study/collections/cohort-001"
    vector_root = exp / "measurement-validation/runs/run-002/focused/scripted-cases"
    vector_names = sorted({item[side] for item in expected["retained_control_pairs"] for side in ("left", "right")})
    input_roots = [capsule, collection, exp / "expansion/frozen/source", args.controls_receipt.resolve(),
                   exp / "snapshots/pilot-v1/source/evaluate.py",
                   exp / "snapshots/pilot-v1/source/mcp_server.py",
                   exp / "snapshots/audit-fixed-v2/source/evaluate.py"]
    input_roots += [vector_root / name for name in vector_names]
    before = {}
    for source in input_roots:
        if not source.exists():
            raise FileNotFoundError(source)
        before.update(inventory(source))
    write(out / "inputs-before.json", before)
    logging.info("Inventoried %d immutable input files before any copied-module import", len(before))
    runtime = out / "runtime/implementation"
    runtime.mkdir(parents=True)
    (runtime / "src/access_study").mkdir(parents=True)
    for source in (capsule / "implementation/src/access_study").glob("*.py"):
        shutil.copyfile(source, runtime / "src/access_study" / source.name)
    for name in ("config.json", "api-contract.json"):
        shutil.copyfile(capsule / "implementation" / name, runtime / name)
    shutil.copyfile(exp / "expansion/frozen/source/oracle.py", runtime / "b_oracle.py")
    (out / "inputs").mkdir()
    shutil.copyfile(args.controls_receipt, out / "inputs/retained-C-controls.json")
    control_hash = digest(args.controls_receipt.read_bytes())
    capsule_manifest = read(capsule / "manifest.json")
    declared_hash = capsule_manifest["files"].get("local-validation.json")
    if declared_hash != control_hash:
        raise RuntimeError("Retained C control receipt not bound by capsule manifest")
    sys.path.insert(0, str(runtime / "src"))
    gate = importlib.import_module("access_study.gate")
    oracle = importlib.import_module("access_study.oracle")
    Harness = importlib.import_module("access_study.harness").Harness
    b_oracle = load_module(runtime / "b_oracle.py", "diagnostic_retained_B_oracle")
    cfg = read(runtime / "config.json")
    mismatches = []

    def expect(label, observed, prescribed):
        if observed != prescribed:
            mismatches.append({"label": label, "expected": prescribed, "observed": observed})
            logging.error("Expectation mismatch %s", label)

    table(out / "phase-field-semantics.csv", maps["phase_fields"])
    table(out / "information-obligations.csv", maps["obligations"])

    # Extraction, not re-execution, of the prespecified controls.
    control_rows = []
    control_receipt = read(out / "inputs/retained-C-controls.json")
    for item in control_receipt["controls"]:
        cell, ledger = item["cell"], item["ledger"]
        rendered = ledger["reference_rendered_messages_NOT_actual_supply"]
        row = {**cell, "policy": item["policy"], "actions": item["actions"],
               "retrieval_calls": ledger["retrieval"]["calls"], "retrieved_documents": ledger["retrieval"]["documents"],
               "retrieval_document_bytes": ledger["retrieval"]["document_bytes"],
               "checks": len(ledger["checks"]), "release_requests": item["outcome"]["observed_prefix_release_requests"],
               "restores": (rendered["categories"].get("driver_restore_verified_and_continuation", {}).get("supplied_messages", 0)
                            if rendered["fully_accounted"] and rendered["closure_verified"] else None),
               "restore_count_basis": "Observed restore-response count in the fully accounted preserved reference-rendered ledger; not participant behavior",
               "success": item["outcome"]["success"], "missed_positive": item["outcome"]["missed_recoverable_opportunity"],
               "reference_rendered_bytes": rendered["bytes"], "byte_mode": rendered["modes"],
               "automatic_input_bytes": ledger["automatic"]["bytes"], "original_control_path": item["path"]}
        control_rows.append(row)
        spec = expected["retained_controls"][item["policy"]]
        actions = spec.get("actions_per_path", spec.get("actions_" + cell["state"] + "_" + cell["regime"]))
        expect(item["path"] + "/actions", item["actions"], actions)
        expect(item["path"] + "/success", row["success"], spec["success"])
        expect(item["path"] + "/checks", row["checks"], spec["checks_per_path"])
        if "retrieval_calls" in spec:
            expect(item["path"] + "/retrievals", row["retrieval_calls"], spec["retrieval_calls"])
        if item["policy"] == "always_hold":
            expect(item["path"] + "/missed_positive", row["missed_positive"], True)
    for policy, spec in expected["retained_controls"].items():
        expect(policy + "/row_count", sum(r["policy"] == policy for r in control_rows), spec["rows"])
    table(out / "retained-C-controls.csv", control_rows)
    write(out / "retained-C-controls.json", {"source_sha256": control_hash, "source_bound_to_capsule": True,
                                             "original_public_archive_omits_receipt": not (capsule / "local-validation.json").exists(),
                                             "rows": control_rows, "rerun": False})
    logging.info("Extracted %d prior control rows without rerunning them", len(control_rows))

    # Manual expected labels pre-exist in expectations.json; frozen outputs are observations.
    semantics = []
    for case in cfg["case_ids"]:
        for variant, spec in expected["C_semantics"].items():
            for label in ("supported", "unsupported"):
                name = "__".join((case, variant, label))
                h = Harness(prepared, {"case": case, "state": "U", "arm": "G", "regime": "distributed"}, out / "semantic-probes" / name)
                pristine = h.context()
                if variant == "authorization_only_revoked":
                    h.state["contract"]["release_authorized"] = False
                elif variant == "protected_note_only_changed":
                    (h.workspace / "note.txt").write_text("Post-review protected-note-only counterfactual.\n")
                context = h.context()
                before_subject = {k: v for k, v in pristine["full_manifest"].items() if k.startswith("source/")}
                after_subject = {k: v for k, v in context["full_manifest"].items() if k.startswith("source/")}
                expect(name + "/subject_unchanged", after_subject, before_subject)
                expect(name + "/evidence_unchanged", context["evidence"], pristine["evidence"])
                expect(name + "/binding_unchanged", context["binding"], pristine["binding"])
                projection, decision, eligible = gate.reconcile(context), gate.gate(context), oracle.supported(context)
                observation = {"technical_reconciliation": projection["technical"], "gate_technical": decision["technical"],
                               "gate_allowed": decision["allowed"], "composite_eligibility": eligible,
                               "expected_historical_finish_technical": "supported" if eligible else "unsupported"}
                expect(name + "/predicate", observation, spec)
                result, error, fatal = h.call("finish", {"technical": label, "disposition": "hold", "release_id": None,
                                                     "reason": "Controlled field-semantics probe outside recipient counts"})
                if error or fatal:
                    raise RuntimeError(result)
                outcome = oracle.evaluate(h.folder, h.close("post_review_semantic_probe"))
                expect(name + "/final_field_accuracy", outcome["accurate_final"], label == spec["expected_historical_finish_technical"])
                semantics.append({"case": case, "variant": variant, "supplied_finish_technical": label, **observation,
                                  "final_field_accuracy": outcome["accurate_final"], "gate_reason": decision["reason"],
                                  "projection_identical_except_runtime": compact_projection(projection) == compact_projection(gate.reconcile(pristine)),
                                  "input_source": "Copied verified U case; only declared mutation applied",
                                  "not_a_recipient_error": True, "path": str(h.folder.relative_to(out))})
    table(out / "C-composite-semantics.csv", semantics)
    write(out / "C-composite-semantics.json", semantics)

    prompt_rows, witness_rows = [], []
    for case in cfg["case_ids"]:
        for state in cfg["states"]:
            g = (capsule / "prompts" / (case + "__" + state + "__G.txt")).read_text()
            p = (capsule / "prompts" / (case + "__" + state + "__P.txt")).read_text()
            expect(case + state + "/prompt_prefix", p.startswith(g + MARKER), True)
            projection = json.loads(p[len(g + MARKER):])
            expect(case + state + "/projection_fields", sorted(projection), ["applicable_ids", "conflict_rule", "technical"])
            prompt_rows.append({"case": case, "state": state, "G_sha256": digest(g.encode()), "P_sha256": digest(p.encode()),
                                "G_is_exact_prefix": p.startswith(g + MARKER), "projection": projection,
                                "authorization_or_preservation_in_projection": False})
            for arm, prompt in (("G", g), ("P", p)):
                for regime in cfg["regimes"]:
                    cell = {"case": case, "state": state, "arm": arm, "regime": regime}
                    name = "__".join((case, state, arm, regime))
                    h = Harness(prepared, cell, out / "information-witnesses" / name)
                    expect(name + "/actual_prompt", h.prompt, prompt)
                    def dispatch(tool, arguments):
                        if tool not in ("list_context", "read_context", "restore_verified", "release", "finish"):
                            raise RuntimeError("Witness cannot execute checks, CLI or any external operation")
                        result, error, fatal = h.call(tool, arguments)
                        if error or fatal:
                            raise RuntimeError(str(result))
                        return result
                    proof = information_policy(prompt, dispatch)
                    metadata = h.close("post_review_exposed_information_witness")
                    outcome = oracle.evaluate(h.folder, metadata)
                    spec_key = regime + "_" + state + ("_" + arm if regime == "distributed" and state == "U" else "_either")
                    path_spec = expected["information_witness"]["conditional_candidate_paths"][spec_key]
                    expect(name + "/actions", h.actions, path_spec["actions"])
                    expect(name + "/retrievals", h.ledger["retrieval"]["calls"], path_spec["retrieval_calls"])
                    expect(name + "/success", outcome["success"], True)
                    expect(name + "/unsupported_requests", outcome["observed_prefix_unsupported_requests"], 0)
                    expect(name + "/unsupported_commits", outcome["observed_prefix_unsupported_commits"], 0)
                    expect(name + "/no_fresh_checks", len(h.ledger["checks"]), 0)
                    witness_rows.append({**cell, "actions": h.actions, "retrieval_calls": h.ledger["retrieval"]["calls"],
                                         "retrieved_documents": h.ledger["retrieval"]["documents"],
                                         "retrieval_document_bytes": h.ledger["retrieval"]["document_bytes"],
                                         "byte_boundary": "Local returned document bytes; not actual model supply or tokens",
                                         "success": outcome["success"], "unsupported_requests": outcome["observed_prefix_unsupported_requests"],
                                         "unsupported_commits": outcome["observed_prefix_unsupported_commits"],
                                         "checks": len(h.ledger["checks"]), "proof": proof,
                                         "not_a_recipient": True, "path": str(h.folder.relative_to(out))})
    table(out / "prompt-information-map.csv", prompt_rows)
    table(out / "information-witnesses.csv", witness_rows)
    write(out / "information-witnesses.json", witness_rows)
    logging.info("Executed %d new bounded exposed-information witnesses; no checks or recipients", len(witness_rows))

    # One counterfactual confirms the information distinction rather than assuming it.
    case = cfg["case_ids"][0]
    cf_prepared = out / "counterfactual-inputs/prepared"
    shutil.copytree(prepared / "cases" / case, cf_prepared / "cases" / case)
    state_path = cf_prepared / "cases" / case / "states/U/state.json"
    state_data = read(state_path)
    state_data["binding"]["dependencies"] += "; post-review-counterfactual-change"
    state_path.write_bytes(canonical(state_data) + b"\n")
    dep_path = cf_prepared / "cases" / case / "states/U/documents/dependencies.json"
    dep_path.write_bytes(canonical(state_data["binding"]) + b"\n")
    counterfactual = {}
    for arm in ("G", "P"):
        base = Harness(prepared, {"case": case, "state": "U", "arm": arm, "regime": "distributed"}, out / "dependency-probe" / (arm + "-baseline"))
        changed = Harness(cf_prepared, {"case": case, "state": "U", "arm": arm, "regime": "distributed"}, out / "dependency-probe" / (arm + "-changed"))
        counterfactual[arm] = {"same_initial_prompt": base.prompt == changed.prompt,
                               "baseline_projection": compact_projection(gate.reconcile(base.context())),
                               "changed_projection": compact_projection(gate.reconcile(changed.context())),
                               "changed_eligibility": oracle.supported(changed.context()),
                               "baseline_prompt_sha256": digest(base.prompt.encode()), "changed_prompt_sha256": digest(changed.prompt.encode())}
        base.close("post_review_render_only")
        changed.close("post_review_render_only")
    same_visible = all((prepared / "cases" / case / "states/U/documents" / name).read_bytes() ==
                       (cf_prepared / "cases" / case / "states/U/documents" / name).read_bytes()
                       for name in ("workspace.json", "contract.json"))
    expect("counterfactual/G_prefix", counterfactual["G"]["same_initial_prompt"], True)
    expect("counterfactual/same_workspace_contract", same_visible, True)
    expect("counterfactual/base_projection", counterfactual["P"]["baseline_projection"]["technical"], "supported")
    expect("counterfactual/changed_projection", counterfactual["P"]["changed_projection"]["technical"], "unknown")
    expect("counterfactual/ineligible", counterfactual["P"]["changed_eligibility"], False)
    write(out / "dependency-information-counterfactual.json", {"case": case, "same_workspace_contract": same_visible,
                                                               "arms": counterfactual, "not_a_recipient": True})

    # Generic views of actual C recipients: no re-execution and no competitor attribution.
    assignments = read(collection / "assignment.json")["assigned"]
    retained = {r["cell"]["opaque_id"]: r for r in read(collection / "evaluation.json")["rows"]}
    recipient_rows = []
    for cell in assignments:
        folder = collection / "sessions" / cell["opaque_id"]
        session = read(folder / "session.json")
        events, audit = oracle.audit_events(folder, session["event_closure"])
        outcome = oracle.evaluate(folder, session["event_closure"])
        finish_event = next((e for e in reversed(events) if e["tool"] == "finish" and not e["error"]), None)
        finish = finish_event["arguments"] if finish_event else None
        requests = [oracle.supported(e["context"]) for e in events if e["tool"] == "release" and not e["validation_error"]]
        commits = [oracle.supported(e["context"]) for e in events if e.get("commit")]
        views = generic_views(finish, "C", requests, commits,
                              oracle.supported(finish_event["context"]) if finish_event else None,
                              {"events_complete": audit["complete"], "final_present": finish is not None})
        final_positive = views["final_only"] == {"present": True, "disposition": "delivered", "technical": "supported"}
        commit_positive = bool(commits) and all(commits)
        full_positive = outcome["success"]
        expect(cell["opaque_id"] + "/retained_outcome", full_positive, retained[cell["opaque_id"]]["success"])
        recipient_rows.append({**cell, "final_only_reported_delivery": final_positive,
                               "commit_only_supported_delivery": commit_positive,
                               "full_verified_success": full_positive,
                               "three_positive_indicators_agree": final_positive == commit_positive == full_positive,
                               "views": views, "source": str(folder.relative_to(artifact))})
    expect("recipient_count", len(recipient_rows), expected["recipient_comparison"]["assigned"])
    table(out / "C-recipient-generic-views.csv", recipient_rows)
    write(out / "C-recipient-generic-views.json", recipient_rows)

    vector_views = {}
    for name in vector_names:
        folder = vector_root / name
        score = read(folder / "scripted-score.json")
        state = read(folder / "state.json")
        fixture = state["fixture"]
        package = {**fixture["package"], "source": (folder / "workspace/component.py").read_text(),
                   "configuration": read(folder / "workspace/configuration.json")}
        context = {"package": package, "candidate_sha256": b_oracle.identity(package),
                   "contract": fixture["contract"], "policy": fixture["policy"],
                   "dependencies": fixture["dependencies"], "evidence": state["evidence"]}
        current = b_oracle.assess(context)
        requests = [e["oracle"]["supported"] for e in score["events"] if e["type"] == "attempt"]
        commits = [e["oracle"]["supported"] for e in score["events"] if e["type"] == "commit"]
        vector_views[name] = {"views": generic_views(score["finish"], "B", requests, commits, current["supported"],
                                                     {"complete_structured": score["complete_structured"], "final_present": score["finish"] is not None}),
                              "current_technical_state": current["technical_state"], "source": str(folder.relative_to(artifact)),
                              "original_protocol_correct_disposition": score["protocol_correct_disposition"],
                              "not_a_recipient": True}
    pairs = []
    for spec in expected["retained_control_pairs"]:
        left, right = vector_views[spec["left"]], vector_views[spec["right"]]
        comparisons = {view + "_equal": left["views"][view] == right["views"][view]
                       for view in ("final_only", "commit_only", "full_event")}
        for key, value in comparisons.items():
            expect(spec["name"] + "/" + key, value, spec[key])
        pairs.append({**spec, "observed": comparisons, "left_views": left, "right_views": right,
                      "scope": "Retained B instrument controls, never C recipient counts"})
    table(out / "retained-control-pair-comparisons.csv", [{"pair": p["name"], **p["observed"]} for p in pairs])
    write(out / "retained-control-pair-comparisons.json", pairs)

    after = {}
    for source in input_roots:
        after.update(inventory(source))
    write(out / "inputs-after.json", after)
    unchanged = before == after
    expect("all_original_inputs_unchanged", unchanged, True)
    summary = {"kind": "post_review_bounded_diagnostic_analysis", "model_calls": 0,
               "historical_controls_rerun": False, "retained_C_control_rows": len(control_rows),
               "new_semantic_finish_probes": len(semantics), "new_exposed_information_witnesses": len(witness_rows),
               "new_dependency_counterfactual_pairs": 1, "C_recipient_records": len(recipient_rows),
               "C_three_indicator_agreements": sum(r["three_positive_indicators_agree"] for r in recipient_rows),
               "retained_B_control_pairs": len(pairs), "all_input_hashes_unchanged": unchanged,
               "input_files_checked": len(before), "expectation_mismatches": mismatches,
               "runtime_seconds": time.monotonic() - start,
               "limits": ["Generic views, not competitor implementations", "Deterministic witnesses, not new recipient evidence",
                          "Projection omission conditional on trusted current technical projection and stable exposed state",
                          "No optimality, broad transfer, new conceptual distinction or favorable empirical P effect established"]}
    write(out / "summary.json", summary)
    logging.info("Completed: %s", summary)
    print(json.dumps(summary, indent=2))
    if mismatches:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
