"""SYNTHETIC UNIT VECTORS ONLY. Never counted as curated public scientific cases."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from access_study.common import ROOT, canonical, sha, write, inventory, subject, settings, safe_child
from access_study.gate import gate
from access_study.oracle import supported, evaluate, load_events
from access_study.prepare import schedule
from access_study.harness import Harness
from access_study.policies import reference
from access_study.cli_bridge import parse_action, usage_from_deltas
from access_study.evaluate import contrasts
from access_study.run_all import claim_once
from access_study.checker import command


def observation(manifest, binding, outcome="pass"):
    result = {"case": "synthetic-unit-only", "tests_run": 1, "failure_count": int(outcome == "fail"),
              "error_count": 0, "skipped": [], "success": outcome == "pass"}
    parsed = {"check": "functional", "scope": settings()["scope"], "subject_sha256": sha(canonical(manifest)),
              "outcome": outcome, "case": "synthetic-unit-only", "adapter_result": result,
              "adapter_returncode": 0 if outcome == "pass" else 1,
              "adapter_stdout": "RESULT_JSON " + json.dumps(result), "adapter_stderr": ""}
    return {"id": "synthetic-unit-pass", "complete": True, "check": "functional", "scope": settings()["scope"],
            "subject_manifest": manifest, "subject_sha256": sha(canonical(manifest)), "binding": binding,
            "outcome": outcome, "runtime_seconds": 0,
            "raw": {"stdout": json.dumps(parsed), "parsed": parsed, "timed_out": False,
                    "exit_code": 0 if outcome == "pass" else 1,
                    "command_template": ["/worker.py", "--check", "functional", "--case", "synthetic-unit-only",
                                         "--subject", sha(canonical(manifest))]}}


def context():
    manifest = {"source/unit.py": sha(b"synthetic never executed")}
    binding = {"criterion": "synthetic-unit-only", "environment": "synthetic-unit-only"}
    return {"full_manifest": {**manifest, "note.txt": sha(b"note")}, "binding": binding,
            "contract": {"case": "synthetic-unit-only", "scope": settings()["scope"], "tests_run": 1,
                         "release_authorized": True, "preserve": {"note.txt": sha(b"note")}},
            "evidence": [observation(manifest, binding)]}


def synthetic_prepared(root):
    """Create source as inert DATA; never execute synthetic package or pretend it is public."""
    case = root / "cases/synthetic-unit-only"
    for label, content in (("before", "before synthetic"), ("after", "after synthetic")):
        (case / label / "source").mkdir(parents=True)
        (case / label / "source/unit.py").write_text(content)
        (case / label / "note.txt").write_text("note")
    snapshots = {label: inventory(case / label) for label in ("before", "after")}
    binding = {"criterion": "synthetic-unit-only", "environment": "synthetic-unit-only"}
    evidence = observation(subject(snapshots["after"]), binding)
    write(case / "case.json", {"snapshots": snapshots, "binding": binding})
    for state in ("R", "U"):
        dest = case / "states" / state
        from access_study.common import copy_verified
        label = "before" if state == "R" else "after"
        copy_verified(case / label, dest / "initial", snapshots[label])
        if state == "U":
            (dest / "initial/note.txt").write_text("changed documentation")
        full = inventory(dest / "initial")
        ctx = {"full_manifest": full, "binding": binding, "evidence": [evidence],
               "contract": {"case": "synthetic-unit-only", "scope": settings()["scope"], "tests_run": 1,
                            "release_authorized": True, "preserve": {"note.txt": full["note.txt"]}}}
        write(dest / "state.json", ctx)
        for name, data in (("workspace.json", {"full_manifest": full}), ("history.json", {"evidence": [evidence]}),
                           ("contract.json", ctx["contract"]), ("dependencies.json", binding)):
            write(dest / "documents" / name, data)
    return root


class PredicateVectors(unittest.TestCase):
    def assert_both(self, ctx, expected):
        self.assertIs(gate(ctx)["allowed"], expected)
        self.assertIs(supported(ctx), expected)

    def test_good_pass(self):
        self.assert_both(context(), True)

    def test_corrected_check_scope_matrix(self):
        for check in ("compile", "physical-fit", "", None, "functional"):
            for scope in ("compile", "physical-fit", settings()["scope"], None):
                with self.subTest(check=check, scope=scope):
                    ctx = context()
                    ctx["evidence"][0]["check"] = check
                    ctx["evidence"][0]["scope"] = scope
                    self.assert_both(ctx, check == "functional" and scope == settings()["scope"])

    def test_raw_provenance_mutations(self):
        mutations = [lambda e: e["raw"].update(stdout="invalid"),
                     lambda e: e["raw"]["parsed"].update(check="compile"),
                     lambda e: e["raw"].update(command_template=["--check", "compile"]),
                     lambda e: e["raw"]["command_template"].extend(["--check", "functional"]),
                     lambda e: e["raw"].update(exit_code=1),
                     lambda e: e["raw"].update(exit_code=False),
                     lambda e: e["raw"].update(timed_out=True),
                     lambda e: e.update(complete=False),
                     lambda e: e.update(subject_sha256="wrong"),
                     lambda e: e.update(binding={"different": True}),
                     lambda e: e.update(outcome="fail")]
        for i, mutation in enumerate(mutations):
            with self.subTest(vector=i):
                ctx = context()
                mutation(ctx["evidence"][0])
                self.assert_both(ctx, False)

    def test_coherent_compile_cannot_pass_functional(self):
        ctx = context()
        record = ctx["evidence"][0]
        record["check"] = "compile"
        record["scope"] = "compile"
        record["raw"]["parsed"].update(check="compile", scope="compile")
        record["raw"]["stdout"] = json.dumps(record["raw"]["parsed"])
        record["raw"]["command_template"][2] = "compile"
        self.assert_both(ctx, False)

    def test_conflict_blocks_regardless_order(self):
        ctx = context()
        ctx["evidence"].append(observation(subject(ctx["full_manifest"]), ctx["binding"], "fail"))
        self.assert_both(ctx, False)
        ctx["evidence"].reverse()
        self.assert_both(ctx, False)

    def test_scoped_vs_full_identity(self):
        ctx = context()
        ctx["full_manifest"]["note.txt"] = sha(b"allowed new note")
        ctx["contract"]["preserve"]["note.txt"] = ctx["full_manifest"]["note.txt"]
        self.assert_both(ctx, True)
        ctx["full_manifest"]["source/unit.py"] = sha(b"changed executable")
        self.assert_both(ctx, False)

    def test_extra_source_file_invalidates(self):
        ctx = context()
        ctx["full_manifest"]["source/extra.py"] = sha(b"new")
        self.assert_both(ctx, False)

    def test_auth_and_note_protected(self):
        ctx = context()
        ctx["contract"]["release_authorized"] = False
        self.assert_both(ctx, False)
        ctx = context()
        ctx["full_manifest"]["note.txt"] = sha(b"tampered")
        self.assert_both(ctx, False)

    def test_missing_and_null_records(self):
        for records in ([], [None], [{}], [{"complete": True}]):
            ctx = context()
            ctx["evidence"] = records
            self.assert_both(ctx, False)


class HarnessVectors(unittest.TestCase):
    def setUp(self):
        temp = ROOT / "local-validation" / "tmp"
        temp.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp)
        self.root = Path(self.temp.name)
        self.prepared = synthetic_prepared(self.root / "prepared")
        self.index = 0

    def tearDown(self):
        self.temp.cleanup()

    def harness(self, state="R", arm="G", regime="distributed"):
        self.index += 1
        return Harness(self.prepared, {"case": "synthetic-unit-only", "state": state, "arm": arm,
                                       "regime": regime, "repetition": "unit"}, self.root / str(self.index))

    def finish(self, h, disposition="hold", technical="unsupported", release_id=None):
        return h.call("finish", {"technical": technical, "disposition": disposition,
                                 "release_id": release_id, "reason": "synthetic unit vector"})

    def test_g_p_same_release_gate(self):
        for arm in ("G", "P"):
            h = self.harness(arm=arm)
            result, error, _ = h.call("release", {})
            self.assertFalse(result["allowed"])
            self.assertFalse(error)
            h.call("restore_verified", {})
            result, _, _ = h.call("release", {})
            self.assertTrue(result["allowed"])

    def test_prompt_and_document_access_parity(self):
        for arm in ("G", "P"):
            b = self.harness(arm=arm, regime="bundled")
            d = self.harness(arm=arm)
            self.assertEqual(b.prompt, d.prompt)
            bundled = b.call("read_context", {})[0]["documents"]
            distributed = [d.call("read_context", {"name": name})[0]["documents"][0]
                           for name in settings()["document_names"]]
            self.assertEqual(bundled, distributed)
            self.assertEqual(b.ledger["retrieval"]["unique_document_bytes"], d.ledger["retrieval"]["unique_document_bytes"])

    def test_reconciliation_acquisition_counted(self):
        g, p = self.harness(arm="G"), self.harness(arm="P")
        self.assertEqual(len(g.ledger["automatic"]["reads"]), 3)
        self.assertEqual(len(p.ledger["automatic"]["reads"]), 4)
        self.assertGreater(p.ledger["automatic"]["bytes"], g.ledger["automatic"]["bytes"])
        self.assertNotIn("projection", g.ledger["automatic"])
        self.assertIn("projection", p.ledger["automatic"])

    def test_restore_note_and_subject(self):
        h = self.harness(state="U")
        before = h.context()
        h.call("restore_verified", {})
        self.assertEqual(before["full_manifest"], h.context()["full_manifest"])
        h = self.harness(state="R")
        note = (h.workspace / "note.txt").read_bytes()
        h.call("restore_verified", {})
        self.assertEqual(note, (h.workspace / "note.txt").read_bytes())
        self.assertTrue(supported(h.context()))

    def test_rejected_parameters_charge_and_log(self):
        h = self.harness()
        for tool, args in (("run_check", {"check": "compile"}), ("read_context", {"name": "../secret"}),
                           ("restore_verified", {"path": "/home"}), ("not_a_tool", {}), ("release", {"override": True})):
            self.assertTrue(h.call(tool, args)[1])
        self.assertEqual(h.actions, 5)
        self.assertEqual(len(load_events(h.folder)), 5)
        self.assertEqual(h.ledger["retrieval"]["errors"], 1)

    def test_hard_action_budget(self):
        h = self.harness()
        for _ in range(32):
            h.call("bad", {})
        with self.assertRaises(TimeoutError):
            h.call("list_context", {})
        self.assertEqual(h.actions, 32)

    def test_no_silent_truncation(self):
        h = self.harness(regime="bundled")
        h.cfg["max_response_bytes"] = 100
        result, error, fatal = h.call("read_context", {})
        self.assertTrue(error)
        self.assertIsNotNone(fatal)
        self.assertEqual(h.ledger["retrieval"]["payload_bytes"], 0)

    def test_repeat_bytes_not_unique(self):
        h = self.harness(regime="bundled")
        h.call("read_context", {})
        unique = h.ledger["retrieval"]["unique_document_bytes"]
        h.call("read_context", {})
        self.assertEqual(h.ledger["retrieval"]["unique_document_bytes"], unique)
        self.assertEqual(h.ledger["retrieval"]["document_bytes"], 2 * unique)
        self.assertEqual(h.ledger["retrieval"]["repeated_documents"], 4)

    def test_hold_is_missed_positive(self):
        for state in ("R", "U"):
            h = self.harness(state=state)
            metadata = reference(h, "always_hold")
            result = evaluate(h.folder, metadata)
            self.assertFalse(result["success"])
            self.assertTrue(result["missed_recoverable_opportunity"])
            self.assertFalse(result["justified_hold"])

    def test_always_restore_is_sufficient(self):
        for state in ("R", "U"):
            h = self.harness(state=state)
            result = evaluate(h.folder, reference(h, "always_restore"))
            self.assertTrue(result["success"])
            self.assertEqual(h.actions, 3)
            self.assertEqual(h.ledger["checks"], [])

    def test_unsafe_request_retained_after_recovery(self):
        h = self.harness()
        h.call("release", {})
        result = evaluate(h.folder, reference(h, "always_restore"))
        self.assertTrue(result["success"])
        self.assertTrue(result["unsupported_request"])
        self.assertTrue(result["recovered_after_unsupported_request"])
        self.assertFalse(result["unsupported_commit"])

    def test_partial_unknown_not_zero(self):
        h = self.harness()
        h.call("list_context", {})
        result = evaluate(h.folder, h.close("timeout"))
        self.assertIsNone(result["success"])
        self.assertIsNone(result["unsupported_request"])
        h = self.harness()
        h.call("release", {})
        result = evaluate(h.folder, h.close("timeout"))
        self.assertTrue(result["unsupported_request"])
        self.assertIsNone(result["success"])

    def test_supported_delivery_without_final_is_not_success(self):
        h = self.harness(state="U")
        h.call("release", {})
        result = evaluate(h.folder, h.close("timeout"))
        self.assertTrue(result["delivery_observed"])
        self.assertIsNone(result["success"])

    def test_inaccurate_final_not_success(self):
        h = self.harness(state="U")
        h.call("release", {})
        self.finish(h, "hold", "unsupported")
        result = evaluate(h.folder, h.close("finished"))
        self.assertFalse(result["success"])
        self.assertFalse(result["accurate_final"])

    def test_snapshot_tamper_detected(self):
        h = self.harness()
        h.call("list_context", {})
        snap = next((h.folder / "snapshots").glob("*/note.txt"))
        snap.chmod(0o644)
        snap.write_text("tampered")
        with self.assertRaises(RuntimeError):
            load_events(h.folder)

    def test_oracle_detects_injected_unsupported_commit(self):
        from access_study.common import copy_verified
        h = self.harness()
        h.call("release", {})
        path = h.folder / "events.jsonl"
        event = json.loads(path.read_text())
        event.pop("event_sha256")
        event["commit"] = "synthetic-bypass"
        event["result"]["allowed"] = True
        copy_verified(h.workspace, h.folder / "releases/synthetic-bypass", event["context"]["full_manifest"])
        event["event_sha256"] = sha(canonical(event))
        path.write_text(json.dumps(event) + "\n")
        result = evaluate(h.folder, {"termination": "synthetic instrument bypass"})
        self.assertTrue(result["unsupported_commit"])
        self.assertTrue(result["unsupported_request"])
        self.assertIsNone(result["success"])

    def test_earlier_unsupported_commit_prevents_later_success(self):
        from access_study.common import copy_verified
        h = self.harness()
        h.call("release", {})
        metadata = reference(h, "always_restore")
        path = h.folder / "events.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines()]
        events[0]["commit"] = "synthetic-early-bypass"
        snapshot = h.folder / "snapshots" / events[0]["snapshot"]
        copy_verified(snapshot, h.folder / "releases/synthetic-early-bypass", events[0]["context"]["full_manifest"])
        previous = None
        for event in events:
            event.pop("event_sha256")
            event["previous_sha256"] = previous
            event["event_sha256"] = sha(canonical(event))
            previous = event["event_sha256"]
        path.write_text("".join(json.dumps(e) + "\n" for e in events))
        # This vector deliberately models a faulty instrument committing an unsafe
        # snapshot, with a coherent closure. Lost-log vectors are tested separately.
        metadata = dict(metadata, last_event_sha256=previous)
        result = evaluate(h.folder, metadata)
        self.assertTrue(result["accurate_final"])
        self.assertTrue(result["delivery_observed"])
        self.assertTrue(result["unsupported_commit"])
        self.assertFalse(result["success"])

    def test_unlaunched_analysis_preserves_missingness(self):
        from access_study.evaluate import evaluate_run
        run = self.root / "synthetic-unlaunched"
        run.mkdir()
        write(run / "assignment.json", {"assigned": schedule(settings())})
        result = evaluate_run(run)
        self.assertEqual(result["flow"]["never_started"], 160)
        self.assertEqual(result["flow"]["final_dispositions"], 0)
        self.assertTrue(all(r["success"] is None and r["context_payload_bytes"] is None for r in result["rows"]))
        self.assertTrue(all(c["equal_case_state_aggregate"]["interaction"] is None for c in result["contrasts"]))

    def test_chain_tamper_detected(self):
        h = self.harness()
        h.call("list_context", {})
        path = h.folder / "events.jsonl"
        event = json.loads(path.read_text())
        event["tool"] = "release"
        path.write_text(json.dumps(event) + "\n")
        with self.assertRaises(RuntimeError):
            load_events(h.folder)

    def test_context_capture_does_not_alias_future_evidence(self):
        h = self.harness()
        before = h.context()
        h.state["evidence"].append({"id": "future"})
        self.assertEqual(len(before["evidence"]), 1)

    def test_synthetic_persistent_transport_and_invalid_action(self):
        from access_study.cli_bridge import execute
        for scenario in ("good", "invalid"):
            h = self.harness()
            result = execute([sys.executable, "-I", str(ROOT / "tests/fake_transport.py"), scenario],
                             h, "synthetic-unit-identity")
            self.assertTrue(result["launched"])
            self.assertEqual(result["errors"], [])
            self.assertEqual(h.actions, 2)
            self.assertTrue(h.finished)
            self.assertEqual(result["usage"]["input_tokens"]["value"], 2)
            events = load_events(h.folder)
            self.assertEqual(events[0]["validation_error"], scenario == "invalid")

    def test_synthetic_transport_stops_on_identity_native_and_quota(self):
        from access_study.cli_bridge import execute
        for scenario in ("identity", "native", "quota"):
            h = self.harness()
            result = execute([sys.executable, "-I", str(ROOT / "tests/fake_transport.py"), scenario],
                             h, "synthetic-unit-identity")
            self.assertTrue(result["errors"])
            self.assertEqual(h.actions, 0)
            self.assertFalse(h.finished)

    def test_synthetic_transport_deadline(self):
        import time
        from access_study.cli_bridge import execute
        h = self.harness()
        h.deadline = time.monotonic() + 0.15
        result = execute([sys.executable, "-I", str(ROOT / "tests/fake_transport.py"), "deadline"],
                         h, "synthetic-unit-identity")
        self.assertTrue(result["timeout"])
        self.assertEqual(h.actions, 0)
        self.assertFalse(h.finished)

    def test_primary_started_preparation_failure_is_noncompletion(self):
        from unittest.mock import patch
        from access_study.session import run_session
        from access_study.evaluate import evaluate_run
        run = self.root / "synthetic-preparation-failure"
        cell = {"case": "synthetic-unit-only", "state": "R", "arm": "P", "regime": "bundled",
                "repetition": 42, "opaque_id": "unit"}
        write(run / "assignment.json", {"assigned": [cell]})
        slot = run / "sessions/unit"
        def fail_preparation(*args, **kwargs):
            self.assertTrue((slot / "slot-start.json").exists())
            raise RuntimeError("synthetic preparation failure")
        with patch("access_study.session.Harness", side_effect=fail_preparation), patch("access_study.session.execute") as provider:
            result = run_session(self.root, {}, cell, slot)
            provider.assert_not_called()
        self.assertFalse(result["transport"]["launched"])
        analysis = evaluate_run(run)
        self.assertEqual(analysis["primary_completion_started_slots"]["denominator"], 1)
        self.assertFalse(analysis["rows"][0]["success"])
        self.assertEqual(analysis["rows"][0]["study_supplied_message_bytes"], 0)
        self.assertEqual(analysis["rows"][0]["primary_completion_cause"], "preparation_failure")
        self.assertIsNone(analysis["rows"][0]["unsupported_request"])

    def test_primary_cap_exhaustion_and_actual_utf8_bytes(self):
        from unittest.mock import patch
        from access_study.session import run_session
        from access_study.evaluate import evaluate_run
        h = self.harness()
        cell = dict(h.cell, opaque_id="cap-unit")
        manifest = {"model_identity": "synthetic-unit-identity", "prompt_hashes": {
                    "synthetic-unit-only__R__G": sha(h.prompt.encode())}}
        run = self.root / "synthetic-cap-run"
        write(run / "assignment.json", {"assigned": [cell]})
        fake_command = [sys.executable, "-I", str(ROOT / "tests/fake_transport.py"), "cap", "--system-prompt", "Unit system: Ω"]
        with patch("access_study.session.command", return_value=fake_command), patch("access_study.session.environment", return_value="synthetic-unit-only"):
            result = run_session(self.root, manifest, cell, run / "sessions/cap-unit")
        self.assertEqual(result["transport"]["termination"], "action_cap")
        self.assertEqual(result["instrument"]["actions"], 32)
        analysis = evaluate_run(run)
        row = analysis["rows"][0]
        self.assertFalse(row["success"])
        self.assertEqual(row["primary_completion_cause"], "action_cap")
        stdin = [json.loads(line) for line in (run / "sessions/cap-unit/stdin.stream.jsonl").read_text().splitlines()]
        expected = len("Unit system: Ω".encode()) + sum(len(x["message"]["content"].encode()) for x in stdin)
        self.assertEqual(row["study_supplied_message_bytes"], expected)
        self.assertGreater(expected, row["context_payload_bytes"])
        self.assertIsNone(row["unsupported_request"])

    def test_missing_lifecycle_not_imputed_zero(self):
        from access_study.evaluate import evaluate_run
        run = self.root / "synthetic-lost-lifecycle"
        cell = dict(self.harness().cell, opaque_id="lost")
        write(run / "assignment.json", {"assigned": [cell]})
        write(run / "sessions/lost/slot-start.json", {"cell": cell})
        analysis = evaluate_run(run)
        self.assertEqual(analysis["flow"]["started_lifecycle_unknown"], 1)
        self.assertIsNone(analysis["rows"][0]["success"])
        self.assertIsNone(analysis["rows"][0]["study_supplied_message_bytes"])

    def test_unknown_delivery_null_and_utf8_not_characters(self):
        from access_study.messages import MessageLedger, measure
        folder = self.root / "synthetic-messages"
        folder.mkdir()
        ledger = MessageLedger(folder)
        first = ledger.begin("initial", "éΩ")
        ledger.end(first, "supplied_to_client")
        self.assertEqual(measure(folder, ledger.close())["bytes"], 4)
        other = self.root / "synthetic-pending-messages"
        other.mkdir()
        pending = MessageLedger(other)
        first = pending.begin("initial", "éΩ")
        pending.end(first, "supplied_to_client")
        pending.begin("driver", "possibly partially supplied")
        result = measure(other, pending.close())
        self.assertIsNone(result["bytes"])
        self.assertEqual(result["known_prefix_bytes"], 4)
        self.assertEqual(result["delivery_unknown"], 1)

    def test_single_use_claim(self):
        claim_once(self.root, {"unit": True})
        with self.assertRaises(FileExistsError):
            claim_once(self.root, {"unit": True})

    def test_paths_and_links(self):
        with self.assertRaises(ValueError):
            safe_child(self.root, "../outside")
        (self.root / "link").symlink_to(self.root / "prepared", target_is_directory=True)
        with self.assertRaises(ValueError):
            safe_child(self.root, "link/cases")


class DesignAndTelemetry(unittest.TestCase):
    def test_schedule_160_balanced_blocks(self):
        rows = schedule(settings())
        self.assertEqual(len(rows), 160)
        self.assertEqual(len({r["opaque_id"] for r in rows}), 160)
        self.assertEqual(rows, schedule(settings()))
        for index in range(0, 160, 4):
            block = rows[index:index + 4]
            self.assertEqual(len({(r["case"], r["state"], r["repetition"]) for r in block}), 1)
            self.assertEqual(len({(r["arm"], r["regime"]) for r in block}), 4)

    def test_usage_missing_is_null(self):
        self.assertIsNone(usage_from_deltas([])["input_tokens"]["value"])
        values = usage_from_deltas([{"model_usage_since_last_result": {"observed": {"inputTokens": 7}}}, {}])
        self.assertIsNone(values["input_tokens"]["value"])
        self.assertEqual(values["input_tokens"]["observed_partial_sum"], 7)
        self.assertEqual(values["input_tokens"]["missing_categories"], 1)

    def test_usage_explicit_deltas_not_cumulative(self):
        records = [{"model_usage_since_last_result": {"observed": {"inputTokens": 7}}, "usage": {"input_tokens": 1000}},
                   {"model_usage_since_last_result": {"observed": {"inputTokens": 3}}, "usage": {"input_tokens": 2000}}]
        self.assertEqual(usage_from_deltas(records)["input_tokens"]["value"], 10)

    def test_parser_rejects_extra_keys(self):
        for text in ('[]', '{}', '{"tool":"finish","arguments":{},"extra":1}', 'not json'):
            with self.assertRaises((ValueError, TypeError)):
                parse_action(text)

    def test_contrast_direction_and_missing(self):
        cfg = {"case_ids": ["a", "b"], "states": ["R"], "arms": ["G", "P"],
               "regimes": ["bundled", "distributed"], "repetitions": [42, 123]}
        rows = []
        for case in cfg["case_ids"]:
            for rep in cfg["repetitions"]:
                for arm, b, d in (("G", 1, 4), ("P", 2, 3)):
                    for regime, value in (("bundled", b), ("distributed", d)):
                        rows.append({"cell": {"case": case, "state": "R", "repetition": rep,
                                              "arm": arm, "regime": regime}, "metric": value})
        result = contrasts(rows, "metric", cfg)
        self.assertEqual(result["equal_case_state_aggregate"], {"delta_G": 3, "delta_P": 1, "interaction": -2})
        rows[0]["metric"] = None
        result = contrasts(rows, "metric", cfg)
        self.assertEqual(len(result["excluded_incomplete_blocks"]), 1)
        self.assertIsNone(result["equal_case_state_aggregate"]["interaction"])
        self.assertEqual(result["observed_subset_NOT_full_suite"]["interaction"]["mean"], -2)
        rows[4]["metric"] = None
        self.assertIsNone(contrasts(rows, "metric", cfg)["equal_case_state_aggregate"]["interaction"])

    def test_no_gate_import_in_oracle(self):
        import ast
        tree = ast.parse((ROOT / "src/access_study/oracle.py").read_text())
        imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertEqual(imports, ["pathlib"])

    def test_sandbox_command_readonly_clean_no_home_network(self):
        cmd = command(Path("/synthetic/source"), Path("/synthetic/tests/adapter.py"), "unit", "hash", settings())
        self.assertIn("--unshare-all", cmd)
        self.assertIn("--clearenv", cmd)
        self.assertIn("--cap-drop", cmd)
        self.assertNotIn("--share-net", cmd)
        self.assertNotIn("/home", cmd)
        self.assertNotIn("--bind", cmd)
        for target in ("/usr", "/lib", "/lib64", "/source", "/tests"):
            self.assertIn(target, cmd)
        self.assertIn("-I", cmd)
        self.assertIn("-S", cmd)

    def test_runner_without_flag_never_reads_authorization_or_calls(self):
        proc = subprocess.run([sys.executable, "-I", str(ROOT / "study.py"), "run", "--frozen", "/absent",
                               "--output", str(ROOT / "never-created"), "--authorization", "/absent"],
                              capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--run absent", proc.stderr)
        self.assertFalse((ROOT / "never-created").exists())

    def test_freeze_without_flag_is_blocked(self):
        argv = [sys.executable, "-I", str(ROOT / "study.py"), "freeze"]
        for key in ("prepared", "validation", "tests", "preflight", "review", "output"):
            argv.extend(["--" + key, "/absent"])
        proc = subprocess.run(argv, capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Freeze not requested", proc.stderr)
