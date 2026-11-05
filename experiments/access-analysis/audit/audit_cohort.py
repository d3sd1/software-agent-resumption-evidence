#!/usr/bin/env python3
"""Independent, read-only reconstruction of the frozen cohort; stdlib only.

No study modules are imported and no checks, recipients or subprocesses are run.
All output is restricted to the directory containing this auditor. The recorded
study evaluation is read only after independent reconstruction is complete.
"""
import argparse
import copy
from collections import Counter, defaultdict
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import itertools
import json
from pathlib import Path


OUTPUT = Path(__file__).resolve().parent
BASE = OUTPUT.parents[1] / "access-study"
ERRORS = []
ASSERTIONS = 0
TREE_CACHE = {}


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def lines(path):
    raw = Path(path).read_bytes()
    expect(not raw or raw.endswith(b"\n"), "finished_jsonl", str(path))
    return [json.loads(line) for line in raw.splitlines()]


def expect(condition, check, details=None):
    global ASSERTIONS
    ASSERTIONS += 1
    if not condition:
        ERRORS.append({"check": check, "details": details})


def inventory(root):
    root = Path(root)
    found = {}
    for p in sorted(root.rglob("*")):
        expect(not p.is_symlink(), "no_symlinks", str(p))
        if p.is_file():
            found[p.relative_to(root).as_posix()] = sha(p.read_bytes())
    return found


def tree(root):
    key = str(root)
    if key not in TREE_CACHE:
        TREE_CACHE[key] = inventory(root)
    return TREE_CACHE[key]


def source(full):
    return {k: v for k, v in full.items() if k.startswith("source/")}


def check_record(record, context):
    """Apply the frozen scoped evidence rules, without gate/oracle imports."""
    try:
        contract, files = context["contract"], source(context["full_manifest"])
        raw = record["raw"]
        parsed = json.loads(raw["stdout"])
        subject_hash = sha(canonical(files))
        if record["complete"] is not True or raw["timed_out"] is not False:
            return None
        expected = {"check": "functional", "scope": contract["scope"], "subject_sha256": subject_hash}
        if any(record.get(k) != v or parsed.get(k) != v for k, v in expected.items()):
            return None
        if record["subject_manifest"] != files or record["binding"] != context["binding"]:
            return None
        if raw["parsed"] != parsed or record["outcome"] != parsed["outcome"]:
            return None
        argv = raw["command_template"]
        for flag, value in (("--check", "functional"), ("--case", contract["case"]), ("--subject", subject_hash)):
            if argv.count(flag) != 1 or argv[argv.index(flag) + 1] != value:
                return None
        outcome = parsed["outcome"]
        if outcome not in ("pass", "fail"):
            return None
        code = 0 if outcome == "pass" else 1
        if type(raw["exit_code"]) is not int or raw["exit_code"] != code or parsed["adapter_returncode"] != code:
            return None
        result = parsed["adapter_result"]
        if parsed["case"] != contract["case"] or result["case"] != contract["case"]:
            return None
        if type(result["tests_run"]) is not int or result["tests_run"] != contract["tests_run"] or result["skipped"] != []:
            return None
        if result["success"] is not (code == 0):
            return None
        if any(type(result[k]) is not int or result[k] < 0 for k in ("failure_count", "error_count")):
            return None
        failures = result["failure_count"] + result["error_count"]
        if (code == 0 and failures != 0) or (code == 1 and failures <= 0):
            return None
        embedded = [json.loads(x[len("RESULT_JSON "):]) for x in parsed["adapter_stdout"].splitlines() if x.startswith("RESULT_JSON ")]
        return outcome if embedded == [result] else None
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def verdict(context):
    outcomes = [check_record(e, context) for e in context["evidence"]]
    technical = "contradicted" if "fail" in outcomes else "supported" if "pass" in outcomes else "unknown"
    files, contract = context["full_manifest"], context["contract"]
    preserved = all(files.get(k) == v for k, v in contract["preserve"].items())
    preserved = preserved and set(files) == set(source(files)) | set(contract["preserve"])
    return technical, contract["release_authorized"] is True and preserved and technical == "supported"


def exact(value):
    value = Fraction(value)
    return {"exact": str(value), "decimal": float(value)}


def contrast(rows, metric, cfg):
    groups = []
    for case, state in itertools.product(cfg["case_ids"], cfg["states"]):
        means, cells = {}, {}
        for arm, regime in itertools.product(cfg["arms"], cfg["regimes"]):
            selected = [r for r in rows if (r["cell"]["case"], r["cell"]["state"], r["cell"]["arm"], r["cell"]["regime"]) == (case, state, arm, regime)]
            values = [int(r[metric]) for r in selected if r[metric] is not None]
            key = arm + "_" + regime
            expect(len(values) == len(cfg["repetitions"]), "contrast_complete_cell", [metric, case, state, key])
            means[key] = Fraction(sum(values), len(values)) if values else None
            cells[key] = {"n": len(values), "sum": sum(values), "mean": exact(means[key]) if values else None}
        if any(x is None for x in means.values()):
            continue
        dg = means["G_distributed"] - means["G_bundled"]
        dp = means["P_distributed"] - means["P_bundled"]
        groups.append({"case": case, "state": state, "cells": cells, "delta_G": exact(dg), "delta_P": exact(dp), "interaction": exact(dp - dg)})
    aggregate = {}
    for name in ("delta_G", "delta_P", "interaction"):
        aggregate[name] = exact(sum(Fraction(g[name]["exact"]) for g in groups) / len(groups)) if groups else None
    return {"metric": metric, "case_state": groups, "equal_case_state_aggregate": aggregate,
            "case_state_count": len(groups), "weighting": "Each of the eight case/state combinations has weight 1/8; five repetitions per cell."}


def audit_session(folder, cell, cap, cfg, manifest):
    ident = cell["opaque_id"]
    session, start, end = (read(folder / n) for n in ("session.json", "slot-start.json", "slot-end.json"))
    instrument = read(folder / "instrument.json")
    expect(start["cell"] == cell == session["cell"] == instrument["cell"], "cell_binding", ident)
    expect(start["boundary"] == "before arm-specific preparation", "slot_boundary", ident)
    expect(sha((folder / "slot-start.json").read_bytes()) == end["slot_start_sha256"] == session["slot_start_sha256"], "start_binding", ident)
    expect(sha((folder / "session.json").read_bytes()) == end["session_sha256"], "end_binding", ident)
    expect(session["instrument"] == instrument, "instrument_receipt_binding", ident)
    launch = read(folder / "launch.json")
    expect(launch["cell"] == cell and launch["model_expected_from_preflight"] == manifest["model_identity"], "launch_binding", ident)
    expect(datetime.fromisoformat(start["at"]) <= datetime.fromisoformat(launch["at"]) <= datetime.fromisoformat(end["at"]), "ordered_slot_times", ident)
    started = datetime.fromisoformat(start["at"])
    wall_from_timestamps = (datetime.fromisoformat(end["at"]) - started).total_seconds()
    expect(wall_from_timestamps <= cfg["session_seconds"] + 0.1, "slot_wall_envelope", ident)
    case_dir = cap / "prepared/cases" / cell["case"]
    state_dir = case_dir / "states" / cell["state"]
    state = read(state_dir / "state.json")
    expected_context = copy.deepcopy(state)
    expect(tree(state_dir / "initial") == state["full_manifest"], "frozen_initial_identity", ident)
    docs = {name: (state_dir / "documents" / name).read_text(encoding="utf-8") for name in cfg["document_names"]}
    events = lines(folder / "events.jsonl")
    counts = Counter(e["tool"] for e in events)
    expect(len(events) <= cfg["action_cap"], "action_envelope", ident)
    previous, unsupported_requests, unsafe_commits = None, 0, 0
    deliveries, final, response_bytes = [], None, 0
    retrieved, seen, payload_bytes, document_bytes, repeated = [], set(), 0, 0, 0
    expected_drivers, gate_results, fresh = [], [], []
    first_release_reused = None
    for index, event in enumerate(events, 1):
        unhashed = dict(event)
        stored = unhashed.pop("event_sha256")
        expect(sha(canonical(unhashed)) == stored and event["previous_sha256"] == previous and event["index"] == index, "event_chain", [ident, index])
        previous = stored
        expect(event["context"] == expected_context, "event_context_from_frozen_sources_and_prior_actions", [ident, index])
        ctx = event["context"]
        snapshot = folder / "snapshots" / event["snapshot"]
        expect(snapshot.is_dir() and tree(snapshot) == ctx["full_manifest"] and sha(canonical(tree(snapshot))) == event["snapshot"], "snapshot_binding", [ident, index])
        expect(0 <= (datetime.fromisoformat(event["at"]) - started).total_seconds() <= cfg["session_seconds"], "event_time_envelope", [ident, index])
        technical, allowed = verdict(ctx)
        tool, args, result = event["tool"], event["arguments"], event["result"]
        expect(not event["error"] and not event["validation_error"] and event["fatal"] is None, "observed_error_free_action", [ident, index])
        response_bytes += len(canonical(result))
        if tool == "list_context":
            expect(result["regime"] == cell["regime"], "directory_regime", ident)
            expect(result["documents"] == [{"name": n, "bytes": len(docs[n].encode("utf-8"))} for n in cfg["document_names"]], "directory_lengths", ident)
        elif tool == "read_context":
            names = cfg["document_names"] if cell["regime"] == "bundled" else [args["name"]]
            expect(result["documents"] == [{"name": n, "content": docs[n]} for n in names], "delivered_document_parity", [ident, index])
            payload_bytes += len(canonical(result))
            for doc in result["documents"]:
                name, size = doc["name"], len(doc["content"].encode("utf-8"))
                document_bytes += size
                repeated += int(name in seen)
                seen.add(name)
                retrieved.append(name)
        elif tool == "restore_verified":
            expected_context["full_manifest"] = {**{k: v for k, v in ctx["full_manifest"].items() if not k.startswith("source/")}, **source(tree(case_dir / "after"))}
            expect(result["restored"] is True and result["note_preserved"] is True and result["executable_manifest"] == source(expected_context["full_manifest"]), "restore_receipt", ident)
        elif tool == "run_check":
            evidence = result["evidence"]
            receipt_dir = folder / "checks" / f"check-{index:03}"
            check_receipt = read(receipt_dir / "receipt.json")
            expect(check_receipt["evidence"] == evidence and (receipt_dir / "stdout.txt").read_text() == evidence["raw"]["stdout"], "fresh_check_source", ident)
            expected_context["evidence"].append(evidence)
            fresh.append(evidence)
        elif tool == "release":
            unsupported_requests += int(not allowed)
            expect(result["allowed"] is allowed and result["technical"] == technical, "independent_gate_verdict", ident)
            gate_results.append(result)
            if event["commit"]:
                actual_release = tree(folder / "releases" / event["commit"])
                expect(actual_release == ctx["full_manifest"] and result["release_id"] == event["commit"], "actual_delivery_binding", ident)
                delivered_context = dict(ctx, full_manifest=actual_release)
                supported = verdict(delivered_context)[1]
                unsafe_commits += int(not supported)
                if supported:
                    deliveries.append(event["commit"])
                if first_release_reused is None:
                    first_release_reused = bool(supported and not fresh and any(check_record(e, delivered_context) == "pass" for e in state["evidence"]))
        elif tool == "finish":
            final = event
        else:
            expect(False, "recognized_action", [ident, tool])
        expect(read(folder / "states" / f"{index:03}.json") == expected_context, "post_action_state", [ident, index])
        if tool != "finish":
            expected_drivers.append((tool, result, event["error"]))
    expect(tree(folder / "workspace") == expected_context["full_manifest"], "final_workspace", ident)
    closure = session["event_closure"]
    expect(closure["actions"] == len(events) == instrument["actions"] and closure["last_event_sha256"] == previous == instrument["last_event_sha256"], "event_closure", ident)
    completed, accurate = final is not None, False
    if final is not None:
        args = final["arguments"]
        accurate = args["technical"] == ("supported" if verdict(final["context"])[1] else "unsupported")
        accurate = accurate and args["disposition"] == ("delivered" if deliveries else "hold")
        accurate = accurate and args["release_id"] == (deliveries[-1] if deliveries else None)
    success = bool(deliveries and accurate and not unsafe_commits)
    expect(end["completion_within_envelope"] is success, "end_completion_crosscheck", ident)
    transport = session["transport"]
    stdin = lines(folder / "stdin.stream.jsonl")
    stdout = lines(folder / "stdout.stream.jsonl")
    inits = [r for r in stdout if r.get("type") == "system" and r.get("subtype") == "init"]
    results = [r for r in stdout if r.get("type") == "result"]
    expect(bool(inits) and all(r.get("model") == manifest["model_identity"] and r.get("tools") == [] for r in inits), "raw_route_and_tool_identity", ident)
    expect(transport["launched"] is True and transport["errors"] == [] and not transport["timeout"] and transport["returncode"] == 0, "transport_completion", ident)
    expect(len(results) == len(events) and all(not r.get("is_error") for r in results), "raw_result_count", ident)
    for event, result in zip(events, results):
        action = json.loads(result["result"])
        expect(action == {"tool": event["tool"], "arguments": event["arguments"]}, "raw_action_matches_event", [ident, event["index"]])
    message_rows = lines(folder / "message-ledger.jsonl")
    contents, statuses, previous = [], {}, None
    for record in message_rows:
        unhashed = dict(record)
        stored = unhashed.pop("record_sha256")
        expect(sha(canonical(unhashed)) == stored and record["previous_sha256"] == previous, "message_chain", ident)
        previous = stored
        if record["event"] == "content":
            expect(record["id"] == len(contents) + 1, "message_sequence", ident)
            expect(sha(record["content"].encode("utf-8")) == record["sha256"] and len(record["content"].encode("utf-8")) == record["utf8_bytes"], "actual_utf8", ident)
            contents.append(record)
        else:
            expect(record["id"] not in statuses and record["status"] == "supplied_to_client", "known_delivery", ident)
            statuses[record["id"]] = record["status"]
    mclosure = session["message_closure"]
    expect(mclosure == transport["message_closure"] and mclosure["log_sha256"] == sha((folder / "message-ledger.jsonl").read_bytes()), "message_closure_hash", ident)
    expect(mclosure["record_count"] == len(message_rows) and mclosure["message_count"] == len(contents) and mclosure["delivery_count"] == len(statuses) and mclosure["last_record_sha256"] == previous, "message_closure_counts", ident)
    expect(contents[0]["content"] == (cap / "system-prompt.txt").read_text(encoding="utf-8"), "frozen_system_content", ident)
    expect(contents[1]["content"] == (folder / "prompt.txt").read_text(encoding="utf-8"), "initial_prompt_log", ident)
    expect(sha(contents[1]["content"].encode()) == manifest["prompt_hashes"]["__".join(cell[k] for k in ("case", "state", "arm"))], "frozen_handoff_content", ident)
    expect([r["content"] for r in contents[1:]] == [r["message"]["content"] for r in stdin], "actual_stream_content_parity", ident)
    expect(len(contents[2:]) == len(expected_drivers), "driver_response_count", ident)
    categories, components = Counter(), Counter()
    timing_delta = 0
    for record in contents:
        categories[record["category"]] += len(record["content"].encode("utf-8"))
    for record, (tool, result, error) in zip(contents[2:], expected_drivers):
        rendered = record["content"]
        parsed = json.loads(rendered)
        expect(record["category"] == "driver_" + tool + "_and_continuation", "driver_category", ident)
        expect(parsed["tool_result"] == {"tool": tool, "result": result, "is_error": error}, "driver_actual_result", ident)
        expect(rendered.encode() == canonical(parsed), "rendering_canonical", ident)
        if tool == "read_context":
            doc_list = result["documents"]
            doc_encoded = sum(len(canonical(d)) for d in doc_list)
            escaped = sum(len(canonical(d["content"])) - 2 for d in doc_list)
            components["retrieval_raw_document_utf8"] += sum(len(d["content"].encode()) for d in doc_list)
            components["retrieval_escaped_content"] += escaped
            components["retrieval_document_structure"] += doc_encoded - escaped
            components["retrieval_result_structure"] += len(canonical(result)) - doc_encoded
            components["retrieval_driver_wrapper_and_continuation"] += len(rendered.encode()) - len(canonical(result))
        if tool == "release":
            normalized = copy.deepcopy(parsed)
            normalized["tool_result"]["result"]["runtime_seconds"] = 0
            timing_delta += len(rendered.encode()) - len(canonical(normalized))
    message_bytes = sum(categories.values())
    expect(message_bytes == len(contents[0]["content"].encode()) + sum(len(r["message"]["content"].encode()) for r in stdin), "stream_byte_sum", ident)
    automatic = lines(folder / "automatic-acquisition.jsonl")
    expected_names = ["history.json", "contract.json", "dependencies.json"] if cell["arm"] == "G" else cfg["document_names"]
    expect([r["name"] for r in automatic] == expected_names, "automatic_read_set", ident)
    automatic_bytes = 0
    for r in automatic:
        raw = (state_dir / "documents" / r["name"]).read_bytes()
        expect(r["bytes"] == len(raw) and r["sha256"] == sha(raw), "automatic_source_binding", ident)
        automatic_bytes += len(raw)
    ledger = instrument["ledger"]
    unique_bytes = sum(len(docs[name].encode()) for name in seen)
    computed_retrieval = {"calls": counts["read_context"], "documents": len(retrieved), "payload_bytes": payload_bytes,
                          "document_bytes": document_bytes, "unique_document_bytes": unique_bytes,
                          "repeated_documents": repeated, "errors": 0}
    expect(ledger["retrieval"] == computed_retrieval, "retrieval_counters", ident)
    expect(ledger["automatic"]["bytes"] == automatic_bytes and ledger["automatic"]["reads"] == [{"name": r["name"], "bytes": r["bytes"]} for r in automatic], "automatic_counters", ident)
    expect(ledger["response_bytes"] == response_bytes and ledger["gates"] == gate_results and len(ledger["checks"]) == len(fresh), "action_cost_counters", ident)
    expect(ledger["automatic"]["initial_prompt_bytes"] == len(contents[1]["content"].encode()), "handoff_bytes_counter", ident)
    if cell["arm"] == "P":
        expect(ledger["automatic"]["projection"]["technical"] == verdict(state)[0], "initial_projection", ident)
        expect(ledger["automatic"]["derived_output_bytes"] == len(canonical(ledger["automatic"]["projection"])), "derived_output_counter", ident)
    result = {"cell": cell, "success": success, "completed": completed, "accurate_final": accurate,
              "delivery_observed": bool(deliveries), "unsupported_request": bool(unsupported_requests), "unsupported_commit": bool(unsafe_commits),
              "unsupported_request_count": unsupported_requests, "unsupported_commit_count": unsafe_commits,
              "known_started": True, "launched": bool(inits), "termination": transport["termination"],
              "actions": len(events), "tool_counts": dict(counts), "action_sequence": [e["tool"] for e in events],
              "retrieved_names_in_order": retrieved, "study_supplied_message_bytes": message_bytes,
              "automatic_bytes": automatic_bytes, "automatic_reads": len(automatic), "context_payload_bytes": payload_bytes,
              "unique_document_bytes": unique_bytes, "retrieved_document_bytes": document_bytes,
              "retrieval_calls": counts["read_context"], "retrieval_documents": len(retrieved), "repeated_documents": repeated,
              "checks": counts["run_check"], "restores": counts["restore_verified"], "release_requests": counts["release"],
              "reused_retained_pass_without_fresh_check": first_release_reused, "categories": dict(categories),
              "byte_components": dict(components), "gate_runtime_serialization_bytes_above_zero": timing_delta,
              "message_bytes_with_gate_runtime_zeroed": message_bytes - timing_delta,
              "wall_seconds": session["wall_seconds"], "timestamp_wall_seconds": wall_from_timestamps,
              "message_unknown": sum(statuses.get(r["id"]) != "supplied_to_client" for r in contents)}
    for k, v in categories.items():
        result["category:" + k] = v
    for k, v in components.items():
        result["component:" + k] = v
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capsule", type=Path, default=BASE / "capsules/cohort-001")
    parser.add_argument("--collection", type=Path, default=BASE / "collections/cohort-001")
    args = parser.parse_args()
    cap, col = args.capsule.resolve(), args.collection.resolve()
    before_cap, before_col = inventory(cap), inventory(col)
    manifest, assignment = read(cap / "manifest.json"), read(col / "assignment.json")
    cfg = read(cap / "implementation/config.json")
    expect(set(before_cap) == set(manifest["files"]) | {"manifest.json"}, "frozen_file_set")
    for name, digest in manifest["files"].items():
        expect(before_cap.get(name) == digest, "frozen_file_hash", name)
    for name, digest in manifest["source_hashes"].items():
        expect(before_cap.get("implementation/" + name) == digest, "frozen_implementation_hash", name)
    expect(assignment["freeze_sha256"] == sha((cap / "manifest.json").read_bytes()), "assignment_manifest_binding")
    cells = assignment["assigned"]
    expect(cells == manifest["planned"], "frozen_assignment_order")
    expected = set(itertools.product(cfg["case_ids"], cfg["states"], cfg["arms"], cfg["regimes"], cfg["repetitions"]))
    actual = [(c["case"], c["state"], c["arm"], c["regime"], c["repetition"]) for c in cells]
    expect(len(cells) == len(expected) == 160 and set(actual) == expected and len(set(actual)) == len(actual), "factorial_frame")
    ids = [c["opaque_id"] for c in cells]
    expect(len(set(ids)) == len(ids) and set(p.name for p in (col / "sessions").iterdir()) == set(ids), "unique_session_ids_and_no_extra_slots")
    projects = {}
    historical_checks = []
    for case in cfg["case_ids"]:
        folder = cap / "prepared/cases" / case
        metadata = read(folder / "case.json")
        projects[case] = metadata["provenance"]["repo"]
        for state_name in cfg["states"]:
            state = read(folder / "states" / state_name / "state.json")
            after = read(folder / "shared-checks/after/receipt.json")["evidence"]
            expect(state["evidence"] == [after], "retained_evidence_matches_original_check", [case, state_name])
            expect(state["binding"] == metadata["binding"], "frozen_state_binding", [case, state_name])
            expect(state["binding"]["adapter_sha256"] == sha((folder / "tests/adapter.py").read_bytes()), "actual_adapter_identity", case)
            expect(state["binding"]["test_files"] == tree(folder / "tests"), "actual_test_inputs", case)
            expect(state["binding"]["worker_sha256"] == sha((cap / "implementation/src/access_study/check_worker.py").read_bytes()), "actual_worker_identity", case)
        for label, expected_outcome in (("before", "fail"), ("after", "pass")):
            receipt_dir = folder / "shared-checks" / label
            receipt = read(receipt_dir / "receipt.json")
            evidence = receipt["evidence"]
            expect((receipt_dir / "stdout.txt").read_text() == evidence["raw"]["stdout"] and (receipt_dir / "stderr.txt").read_text() == evidence["raw"]["stderr"], "raw_predecessor_stream", [case, label])
            state = read(folder / "states/U/state.json")
            context = dict(state, full_manifest=tree(folder / label))
            expect(check_record(evidence, context) == expected_outcome, "frozen_before_fail_after_pass", [case, label])
            historical_checks.append({"case": case, "snapshot": label, "outcome": expected_outcome})
    expect(len(set(projects.values())) == 3, "three_projects")
    prompt_pairs = []
    system_content = (cap / "system-prompt.txt").read_text(encoding="utf-8")
    expect(sha(system_content.encode()) == manifest["system_prompt_sha256"], "system_prompt_manifest_binding")
    for case, state_name in itertools.product(cfg["case_ids"], cfg["states"]):
        key_g, key_p = f"{case}__{state_name}__G", f"{case}__{state_name}__P"
        g = (cap / "prompts" / (key_g + ".txt")).read_text(encoding="utf-8")
        p = (cap / "prompts" / (key_p + ".txt")).read_text(encoding="utf-8")
        expect(sha(g.encode()) == manifest["prompt_hashes"][key_g] and sha(p.encode()) == manifest["prompt_hashes"][key_p], "prompt_pair_hashes", [case, state_name])
        expect(p.startswith(g), "P_retains_full_G_handoff", [case, state_name])
        suffix = p[len(g):]
        label = "Derived current-applicability projection (not an independent check): "
        expect(suffix.startswith(label), "P_only_appended_projection", [case, state_name])
        projection = json.loads(suffix[len(label):])
        expected_technical = verdict(read(cap / "prepared/cases" / case / "states" / state_name / "state.json"))[0]
        expect(projection["technical"] == expected_technical, "frozen_projection_matches_state", [case, state_name])
        expect("A fresh check or ritual inspection is not mandatory. Obtain sufficient current evidence." in g, "optional_inspection_clause_present", [case, state_name])
        prompt_pairs.append({"case": case, "state": state_name, "G_sha256": sha(g.encode()), "P_sha256": sha(p.encode()),
                             "G_utf8_bytes": len(g.encode()), "P_utf8_bytes": len(p.encode()), "G_is_exact_prefix_of_P": p.startswith(g),
                             "P_only_suffix_utf8_bytes": len(suffix.encode()), "P_only_suffix_exact": suffix})
    prompt_audit = {"system_sha256": sha(system_content.encode()), "system_utf8_bytes": len(system_content.encode()),
                    "pairs": prompt_pairs,
                    "instruction_interpretation": "No literal requirement to retrieve all four documents or to run a fresh check. The shared handoff explicitly says ritual inspection is not mandatory, but strongly guides comparison of workspace entries, historical evidence, contract and dependencies and checking contradictions. Complete retrieval is an observed policy under that guidance, not an unprompted reasoning effect.",
                    "exact_shared_instruction": "A fresh check or ritual inspection is not mandatory. Obtain sufficient current evidence.",
                    "exact_shared_guidance": "Compare workspace.json executable entries (not its whole-release digest) with that record; contract.json specifies authorization/protected files and dependencies.json binds the test and environment.",
                    "assigned_interface": "The same within-arm initial content describes both retrieval schemas; the directory response identifies the assigned bundled/distributed interface.",
                    "actual_exposure": "Every session's logged initial content and driver content were cross-checked against frozen hashes and stdin stream content, respectively."}
    flow = lines(col / "flow.jsonl")
    attempts = [r["cell"]["opaque_id"] for r in flow if r["event"] == "launch_attempt"]
    returned = [r["id"] for r in flow if r["event"] == "session_returned"]
    expect(Counter(attempts) == Counter(ids) == Counter(returned), "flow_once_per_slot")
    rows = [audit_session(col / "sessions" / cell["opaque_id"], cell, cap, cfg, manifest) for cell in cells]
    categories = sorted({name for r in rows for name in r["categories"]})
    components = sorted({name for r in rows for name in r["byte_components"]})
    for r in rows:
        for name in categories:
            r.setdefault("category:" + name, 0)
        for name in components:
            r.setdefault("component:" + name, 0)
    metrics = ["success", "study_supplied_message_bytes", "automatic_bytes", "message_bytes_with_gate_runtime_zeroed", "gate_runtime_serialization_bytes_above_zero"]
    metrics += ["category:" + name for name in categories] + ["component:" + name for name in components]
    contrasts = {name: contrast(rows, name, cfg) for name in metrics}
    group_summaries = []
    for arm, regime in itertools.product(cfg["arms"], cfg["regimes"]):
        selected = [r for r in rows if (r["cell"]["arm"], r["cell"]["regime"]) == (arm, regime)]
        sums = {k: sum(int(r[k]) for r in selected) for k in ("success", "study_supplied_message_bytes", "automatic_bytes", "actions", "retrieval_calls", "checks", "restores", "unique_document_bytes")}
        group_summaries.append({"arm": arm, "regime": regime, "n": len(selected), "sums": sums,
                                "means": {k: exact(Fraction(v, len(selected))) for k, v in sums.items()},
                                "category_sums": dict(sum((Counter(r["categories"]) for r in selected), Counter()))})
    # Only now consult the original derived evaluation, never as the source of truth.
    reported = read(col / "evaluation.json")
    reported_rows = {r["cell"]["opaque_id"]: r for r in reported["rows"]}
    for r in rows:
        prior = reported_rows[r["cell"]["opaque_id"]]
        for key in ("success", "study_supplied_message_bytes", "automatic_bytes", "context_payload_bytes", "unique_document_bytes", "repeated_documents", "retrieval_calls", "checks", "release_requests", "unsupported_request", "unsupported_commit"):
            expect(r[key] == prior[key], "reported_row_agrees", [r["cell"]["opaque_id"], key, r[key], prior[key]])
    for metric in ("success", "study_supplied_message_bytes", "automatic_bytes"):
        old = next(x for x in reported["contrasts"] if x["metric"] == metric)
        for name in ("delta_G", "delta_P", "interaction"):
            expect(abs(old["equal_case_state_aggregate"][name] - contrasts[metric]["equal_case_state_aggregate"][name]["decimal"]) < 1e-9, "reported_aggregate_agrees", [metric, name])
        for group in contrasts[metric]["case_state"]:
            old_group = next(g for g in old["case_state"] if (g["case"], g["state"]) == (group["case"], group["state"]))
            for name in ("delta_G", "delta_P", "interaction"):
                expect(abs(old_group[name] - group[name]["decimal"]) < 1e-9, "reported_case_state_agrees", [metric, group["case"], group["state"], name])
    reconstructed_flow = {"assigned": len(cells), "known_started": len(rows), "auditable_started": len(rows),
                          "completion_known": len(rows), "completion_unknown": 0, "workload_known": len(rows), "workload_unknown": 0,
                          "recipient_launched": sum(r["launched"] for r in rows), "launch_unknown": 0,
                          "final_dispositions": sum(r["completed"] for r in rows), "never_started": len(cells) - len(rows),
                          "lifecycle_unknown": 0, "started_lifecycle_unknown": 0,
                          "operationally_incomplete": sum(not r["completed"] for r in rows), "supported_completions": sum(r["success"] for r in rows)}
    # Zero missingness is certified only if every above binding/completeness check passes.
    for key, value in reconstructed_flow.items():
        expect(reported["flow"][key] == value, "reported_flow_agrees", [key, value, reported["flow"][key]])
    primary_completion = {"numerator": sum(r["success"] for r in rows), "denominator": len(rows)}
    expect(all(reported["primary_completion_started_slots"][k] == v for k, v in primary_completion.items()), "reported_primary_completion_agrees")
    read_order_counts = Counter((r["cell"]["arm"], tuple(r["retrieved_names_in_order"])) for r in rows if r["cell"]["regime"] == "distributed")
    tool_counts = sum((Counter(r["tool_counts"]) for r in rows), Counter())
    totals = {k: sum(int(r[k]) for r in rows) for k in ("success", "completed", "accurate_final", "delivery_observed", "unsupported_request_count", "unsupported_commit_count", "known_started", "launched", "actions", "study_supplied_message_bytes", "automatic_bytes", "automatic_reads", "context_payload_bytes", "unique_document_bytes", "retrieved_document_bytes", "retrieval_calls", "retrieval_documents", "repeated_documents", "checks", "restores", "release_requests", "reused_retained_pass_without_fresh_check", "message_unknown")}
    totals["tool_counts"] = dict(tool_counts)
    totals["category_bytes"] = dict(sum((Counter(r["categories"]) for r in rows), Counter()))
    totals["session_wall_seconds_sum"] = sum(r["wall_seconds"] for r in rows)
    sequences = Counter(tuple(r["action_sequence"]) for r in rows)
    execution = read(col / "execution.json")
    expect(execution["attempted"] == len(attempts) and execution["unlaunched"] == 0 and execution["retries"] == 0, "execution_flow_agrees")
    expect(execution["wall_seconds"] + execution["shared_preflight_seconds"] < cfg["global_seconds"], "recorded_global_envelope")
    after_cap, after_col = inventory(cap), inventory(col)
    expect(before_cap == after_cap, "capsule_unchanged_during_audit")
    expect(before_col == after_col, "collection_unchanged_during_audit")
    receipt = {"schema": "independent-cohort-audit-v1", "at": datetime.now(timezone.utc).isoformat(),
               "auditor_sha256": sha(Path(__file__).read_bytes()), "imports_study_modules": False, "model_calls": 0, "checks_executed": 0,
               "capsule": str(cap), "collection": str(col), "manifest_sha256": sha((cap / "manifest.json").read_bytes()),
               "protocol_sha256": sha((cap / "protocol-v1.md").read_bytes()),
               "input_inventory": {"capsule_files": len(before_cap), "capsule_tree_sha256": sha(canonical(before_cap)),
                                   "collection_files": len(before_col), "collection_tree_sha256": sha(canonical(before_col)),
                                   "unchanged_after_audit": before_cap == after_cap and before_col == after_col},
               "assertions": ASSERTIONS, "passed": not ERRORS, "errors": ERRORS,
               "frame": {"assigned": len(cells), "case_projects": projects, "states": cfg["states"], "arms": cfg["arms"],
                         "regimes": cfg["regimes"], "repetitions": cfg["repetitions"], "case_state_blocks": 8},
               "prompt_audit": prompt_audit, "reconstructed_flow": reconstructed_flow, "primary_completion_started_slots": primary_completion,
               "distributed_document_orders": [{"arm": key[0], "documents": list(key[1]), "sessions": count} for key, count in sorted(read_order_counts.items())],
               "shared_check_records": historical_checks, "totals": totals, "arm_regime": group_summaries,
               "action_sequences": [{"actions": list(k), "count": v} for k, v in sorted(sequences.items())],
               "contrasts": contrasts, "sessions": rows, "execution_report_crosschecked": execution,
               "limits": ["Single fixed cohort of authored recoverable tasks; no population inference or power claim.",
                          "Checks are audited from retained raw execution records, not rerun by this auditor.",
                          "Supply means the recorded driver-to-client boundary, not independently observed internal model attention or reasoning.",
                          "The system-prompt content is bound to the frozen file and message ledger; no independent OS argv capture is available in launch.json.",
                          "Gate-runtime-zeroed bytes are a diagnostic decomposition, not a replacement for the prespecified actual-byte endpoint.",
                          "Timing numeric serialization and fixed-length release identifiers are instrument fields, not participant substantive choices.",
                          "Shared authorship/host trust remains; independent implementation does not establish independent experimental replication.",
                          "No p-values, confidence intervals, billing inference, or efficiency inference from bytes."]}
    (OUTPUT / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": not ERRORS, "assertions": ASSERTIONS, "errors": ERRORS[:30], "totals": totals,
                      "primary_contrasts": {k: contrasts[k]["equal_case_state_aggregate"] for k in metrics[:5]}}, indent=2))
    return 0 if not ERRORS else 1


if __name__ == "__main__":
    raise SystemExit(main())
