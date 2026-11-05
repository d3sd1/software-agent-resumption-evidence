"""Synthetic persistence-loss regressions. No public case or participant invocation."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from access_study.common import ROOT, write, read, canonical, sha
from access_study.harness import Harness
from access_study.session import run_session
from access_study.oracle import evaluate as event_evaluate
from access_study.evaluate import evaluate_run
from access_study.messages import MessageLedger, measure
from test_instrument import synthetic_prepared


class ClosureAuditProof(unittest.TestCase):
    def setUp(self):
        temp_root = ROOT / "local-validation/tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.root = Path(self.temp.name)
        self.prepared = synthetic_prepared(self.root / "prepared")
        self.index = 0

    def tearDown(self):
        self.temp.cleanup()

    def slot(self, scenario="deliver"):
        self.index += 1
        cell = {"case": "synthetic-unit-only", "state": "R", "arm": "G", "regime": "distributed",
                "repetition": 42, "opaque_id": "synthetic-slot"}
        rendering = Harness(self.prepared, cell, self.root / f"render-{self.index}")
        manifest = {"model_identity": "synthetic-unit-identity", "prompt_hashes": {
                    "synthetic-unit-only__R__G": sha(rendering.prompt.encode())}}
        run = self.root / f"run-{self.index}"
        write(run / "assignment.json", {"assigned": [cell]})
        folder = run / "sessions/synthetic-slot"
        command = [sys.executable, "-I", str(ROOT / "tests/fake_transport.py"), scenario,
                   "--system-prompt", "Synthetic system: Ω"]
        with patch("access_study.session.command", return_value=command), patch(
                "access_study.session.environment", return_value="synthetic-unit-only"):
            metadata = run_session(self.root, manifest, cell, folder)
        self.assertEqual(metadata["transport"]["errors"], [])
        self.assertTrue(event_evaluate(folder, metadata["event_closure"])["success"])
        self.assertEqual(metadata["instrument"]["actions"], 4 if scenario == "unsafe_then_deliver" else 3)
        return run, folder, metadata

    def two_messages(self):
        self.index += 1
        folder = self.root / f"messages-{self.index}"
        folder.mkdir()
        ledger = MessageLedger(folder)
        for content in ("é", "x" * 1890):
            ident = ledger.begin("synthetic_driver", content)
            ledger.end(ident, "supplied_to_client")
        closure = ledger.close()
        self.assertEqual(measure(folder, closure)["bytes"], 1892)
        return folder, closure

    def test_intact_positive_slot_binds_both_closures(self):
        run, folder, metadata = self.slot()
        result = evaluate_run(run)
        row, flow = result["rows"][0], result["flow"]
        self.assertTrue(row["success"])
        self.assertEqual(flow["known_started"], 1)
        self.assertEqual(flow["completion_known"], 1)
        self.assertEqual(flow["completion_unknown"], 0)
        self.assertEqual(flow["workload_known"], 1)
        self.assertEqual(flow["workload_unknown"], 0)
        self.assertEqual(row["study_supplied_message_bytes"], metadata["study_messages"]["bytes"])
        end = read(folder / "slot-end.json")
        self.assertEqual(end["session_sha256"], sha((folder / "session.json").read_bytes()))
        self.assertTrue(row["event_audit"]["complete"])
        self.assertTrue(row["study_message_ledger"]["closure_verified"])

    def test_missing_truncated_empty_extra_or_rehashed_events_are_unknown(self):
        for mutation in ("missing", "prefix", "empty", "extra", "terminal_rehashed"):
            with self.subTest(mutation=mutation):
                run, folder, metadata = self.slot()
                receipts = {name: (folder / name).read_bytes() for name in ("slot-start.json", "slot-end.json", "session.json", "instrument.json")}
                path = folder / "events.jsonl"
                lines = path.read_bytes().splitlines(keepends=True)
                if mutation == "missing":
                    path.unlink()
                elif mutation == "prefix":
                    path.write_bytes(lines[0])
                elif mutation == "empty":
                    path.write_bytes(b"")
                elif mutation == "extra":
                    path.write_bytes(b"".join(lines + [lines[0]]))
                else:
                    final = json.loads(lines[-1])
                    final.pop("event_sha256")
                    final["arguments"]["reason"] = "synthetic same-count mutation"
                    final["event_sha256"] = sha(canonical(final))
                    path.write_bytes(b"".join(lines[:-1]) + canonical(final) + b"\n")
                for name, original in receipts.items():
                    self.assertEqual((folder / name).read_bytes(), original)
                result = evaluate_run(run)
                row, flow = result["rows"][0], result["flow"]
                self.assertIsNone(row["success"])
                self.assertEqual(row["primary_completion_cause"], "event_record_unknown")
                self.assertEqual(flow["known_started"], 1)
                self.assertEqual(flow["auditable_started"], 1)
                self.assertEqual(flow["completion_unknown"], 1)
                self.assertEqual(flow["completion_known"], 0)
                self.assertEqual(flow["operationally_incomplete"], 0)
                self.assertEqual(flow["workload_known"], 1)
                primary = result["primary_completion_started_slots"]
                self.assertEqual(primary["denominator"], 1)
                self.assertIsNone(primary["numerator"])
                self.assertEqual(primary["observed_noncompletions"], 0)
                self.assertTrue(row["event_audit"]["errors"])

    def test_verified_unsafe_prefix_survives_lost_tail(self):
        run, folder, _ = self.slot("unsafe_then_deliver")
        path = folder / "events.jsonl"
        path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])
        result = evaluate_run(run)
        row = result["rows"][0]
        self.assertIsNone(row["success"])
        self.assertTrue(row["observed_prefix"]["unsupported_request"])
        self.assertEqual(row["observed_prefix"]["observed_prefix_unsupported_requests"], 1)
        self.assertIsNone(row["observed_prefix"]["unsupported_commit"])
        self.assertEqual(row["event_audit"]["verified_prefix_actions"], 1)

    def test_message_tail_loss_empty_and_absence_never_become_known_zero(self):
        for mutation, prefix in (("prefix", 2), ("empty", 0), ("missing", 0)):
            with self.subTest(mutation=mutation):
                folder, closure = self.two_messages()
                path = folder / "message-ledger.jsonl"
                if mutation == "prefix":
                    path.write_bytes(b"".join(path.read_bytes().splitlines(keepends=True)[:2]))
                elif mutation == "empty":
                    path.write_bytes(b"")
                else:
                    path.unlink()
                result = measure(folder, closure)
                self.assertIsNone(result["bytes"])
                self.assertFalse(result["fully_accounted"])
                self.assertFalse(result["closure_verified"])
                self.assertEqual(result["known_prefix_bytes"], prefix)
                self.assertTrue(result["audit_errors"])

    def test_intact_ledger_without_closure_cannot_certify_completeness(self):
        folder, _ = self.two_messages()
        result = measure(folder)
        self.assertIsNone(result["bytes"])
        self.assertEqual(result["known_prefix_bytes"], 1892)
        self.assertIn("missing_or_invalid_message_closure", result["audit_errors"])

    def test_explicit_closed_zero_is_distinct_from_lost_empty_log(self):
        folder = self.root / "explicit-zero"
        folder.mkdir()
        ledger = MessageLedger(folder)
        closure = ledger.close()
        self.assertEqual(measure(folder, closure)["bytes"], 0)
        self.assertTrue(measure(folder, closure)["fully_accounted"])
        (folder / "message-ledger.jsonl").unlink()
        self.assertIsNone(measure(folder, closure)["bytes"])
        self.assertFalse(measure(folder, closure)["fully_accounted"])

    def test_pending_delivery_keeps_known_prefix_but_unknown_total(self):
        folder = self.root / "partial-delivery"
        folder.mkdir()
        ledger = MessageLedger(folder)
        ident = ledger.begin("initial", "é")
        ledger.end(ident, "supplied_to_client")
        ledger.begin("driver", "uncertain write")
        result = measure(folder, ledger.close())
        self.assertTrue(result["closure_verified"])
        self.assertFalse(result["fully_accounted"])
        self.assertEqual(result["known_prefix_bytes"], 2)
        self.assertEqual(result["delivery_unknown"], 1)
        self.assertIsNone(result["bytes"])

    def test_ledger_cannot_append_after_closure(self):
        folder = self.root / "closed-ledger"
        folder.mkdir()
        ledger = MessageLedger(folder)
        ledger.close()
        with self.assertRaises(RuntimeError):
            ledger.begin("driver", "late content")

    def test_utf8_corruption_preserves_completion_safety_and_denominator(self):
        run, folder, _ = self.slot("unsafe_then_deliver")
        path = folder / "message-ledger.jsonl"
        lines = path.read_bytes().splitlines(keepends=True)
        event = json.loads(lines[0])
        event["utf8_bytes"] += 1
        path.write_bytes(canonical(event) + b"\n" + b"".join(lines[1:]))
        result = evaluate_run(run)
        row, flow = result["rows"][0], result["flow"]
        self.assertTrue(row["success"])
        self.assertTrue(row["unsupported_request"])
        self.assertFalse(row["unsupported_commit"])
        self.assertEqual(flow["known_started"], 1)
        self.assertEqual(flow["completion_known"], 1)
        self.assertEqual(flow["completion_unknown"], 0)
        self.assertEqual(flow["workload_unknown"], 1)
        self.assertIsNone(row["study_supplied_message_bytes"])
        self.assertEqual(result["primary_completion_started_slots"]["numerator"], 1)
        self.assertEqual(result["primary_completion_started_slots"]["denominator"], 1)

    def test_measure_exception_is_isolated_from_valid_outcome(self):
        run, _, _ = self.slot()
        with patch("access_study.evaluate.measure", side_effect=RuntimeError("synthetic byte failure")):
            result = evaluate_run(run)
        self.assertTrue(result["rows"][0]["success"])
        self.assertIsNone(result["rows"][0]["study_supplied_message_bytes"])
        self.assertEqual(result["flow"]["auditable_started"], 1)
        self.assertEqual(result["flow"]["completion_known"], 1)
        self.assertEqual(result["flow"]["workload_unknown"], 1)

    def test_message_loss_does_not_change_valid_event_completion(self):
        for mutation in ("prefix", "empty", "missing"):
            with self.subTest(mutation=mutation):
                run, folder, _ = self.slot()
                path = folder / "message-ledger.jsonl"
                if mutation == "prefix":
                    path.write_bytes(b"".join(path.read_bytes().splitlines(keepends=True)[:2]))
                elif mutation == "empty":
                    path.write_bytes(b"")
                else:
                    path.unlink()
                result = evaluate_run(run)
                self.assertTrue(result["rows"][0]["success"])
                self.assertIsNone(result["rows"][0]["study_supplied_message_bytes"])
                self.assertEqual(result["flow"]["known_started"], 1)
                self.assertEqual(result["flow"]["completion_known"], 1)
                self.assertEqual(result["flow"]["workload_unknown"], 1)

    def test_both_audit_failures_remain_separate(self):
        run, folder, _ = self.slot()
        (folder / "events.jsonl").unlink()
        (folder / "message-ledger.jsonl").unlink()
        result = evaluate_run(run)
        self.assertEqual(result["flow"]["known_started"], 1)
        self.assertEqual(result["flow"]["completion_unknown"], 1)
        self.assertEqual(result["flow"]["workload_unknown"], 1)
        self.assertIsNone(result["rows"][0]["success"])
        self.assertIsNone(result["rows"][0]["study_supplied_message_bytes"])
