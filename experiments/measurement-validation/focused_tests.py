"""Scripted measurement checks. This module never launches a participant client."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from common import read_json, write_json
from controls import gate, reconciliation
from domain import config, package_bytes
from evaluate import score, summary
from harness import FixtureTools, prepare_run
from oracle import assess
from cli_bridge import usage_from_deltas

HERE = Path(__file__).resolve().parent
EXPANSION = HERE.parent / "expansion"
SPEC = {case["id"]: case for case in read_json(HERE / "cases.json")["cases"]}
OBSERVATIONS = []
OUTPUT = None


class MeasurementTests(unittest.TestCase):
    def tools(self, family="unrelated-change-valid", arm="G"):
        cases = read_json(EXPANSION / "fixture-manifest.json")["cases"]
        case = next(c for c in cases if c["family"] == family and c["fixture_order_seed"] == 42)
        fixture = read_json(EXPANSION / "fixtures" / case["case_id"] / "fixture.json")
        folder = OUTPUT / self._testMethodName
        prepare_run(folder, fixture, arm)
        self.folder = folder
        self.family, self.arm = family, arm
        return FixtureTools(folder)

    def call(self, tools, name, args=None):
        result, error = tools.call(name, args or {})
        self.assertFalse(error, result)
        return result

    def finish(self, tools, status="hold", assessment="unknown", reason="physical_unobservable"):
        self.call(tools, "finish", {"status": status, "assessment": assessment, "reason": reason})

    def score(self, tools, usage=None):
        metadata = {"launched": True, "completed_controller": True, "completed_cli": False,
                    "errors": [], "diagnostic_scripted_validation_not_participant": True}
        if usage is not None:
            metadata["usage_for_scoring"] = usage
        write_json(tools.folder / "session.json", metadata)
        row = score({"opaque_id": tools.folder.name, "family": self.family, "arm": self.arm},
                    tools.folder, config(), is_model=False)
        write_json(tools.folder / "scripted-score.json", row)
        return row

    def observe(self, identifier, observed):
        spec = SPEC[identifier]
        expected = spec["expected"]
        actual = {key: observed[key] for key in expected}
        record = {**spec, "observed": actual, "matches_expectation": actual == expected,
                  "test": self.id(), "implementation": "expansion/oracle.py; expansion/controls.py; expansion/evaluate.py",
                  "retained_case": str(self.folder.relative_to(HERE)) if hasattr(self, "folder") else None}
        OBSERVATIONS.append(record)
        self.assertEqual(actual, expected, identifier)

    def technical(self, context):
        return {"technical_state": assess(context)["technical_state"], "gate_allowed": gate(context)["allowed"]}

    def test_supported_release(self):
        tools = self.tools()
        self.call(tools, "request_release")
        self.finish(tools, "released", "supported", "completed")
        self.observe("supported-release", self.score(tools))

    def test_unsupported_then_correct_hold(self):
        tools = self.tools("unobservable-physical", "B0")
        self.call(tools, "request_release")
        self.finish(tools)
        self.observe("unsupported-then-hold", {**self.score(tools), "sink_count": len(list((tools.folder / "release_sink").iterdir()))})

    def test_correct_hold_without_commit(self):
        tools = self.tools("unobservable-physical", "B0")
        self.finish(tools)
        self.observe("hold-only", self.score(tools))

    def test_enforced_block(self):
        tools = self.tools("unobservable-physical", "G")
        self.call(tools, "request_release")
        self.finish(tools)
        self.observe("enforced-block", self.score(tools))

    def test_snapshot_preserved_after_edit(self):
        tools = self.tools()
        payload = package_bytes(tools.package())
        self.call(tools, "request_release")
        self.call(tools, "repair_component", {"multiplier": 0, "offset": 0})
        event = json.loads((tools.folder / "release-events.jsonl").read_text().splitlines()[0])
        sink = next((tools.folder / "release_sink").iterdir())
        self.observe("snapshot-preserved", {**self.score(tools), "sink_matches_event": sink.read_bytes() == payload,
                     "workspace_differs": package_bytes(tools.package()) != payload,
                     "event_supported": assess(event["context"])["supported"]})

    def test_snapshot_tampering_detection(self):
        tools = self.tools()
        self.call(tools, "request_release")
        next((tools.folder / "release_sink").iterdir()).write_bytes(b"synthetic corrupted sink")
        row = self.score(tools)
        reasons = [reason for e in row["events"] if e["type"] == "commit" for reason in e["oracle"]["reasons"]]
        self.observe("snapshot-tampered", {**row, "snapshot_mismatch": "snapshot_mismatch" in reasons})

    def test_stale_failure_repair_sequence(self):
        tools = self.tools("untracked-config-drift")
        self.observe("stale-before-check", self.technical(tools.context()))
        result = self.call(tools, "run_check", {"name": "functional"})["evidence"]
        self.observe("failure-after-check", {**self.technical(tools.context()), "outcome": result["outcome"], "exit_code": result["raw"]["exit_code"]})
        self.call(tools, "repair_component", {"multiplier": tools.fixture["contract"]["target_percent"], "offset": 0})
        result = self.call(tools, "run_check", {"name": "functional"})["evidence"]
        self.observe("repair-recheck", {**self.technical(tools.context()), "outcome": result["outcome"], "exit_code": result["raw"]["exit_code"]})

    def test_authorization_separate(self):
        tools = self.tools()
        tools.fixture["policy"]["release"] = False
        state = self.technical(tools.context())
        self.call(tools, "request_release")
        self.finish(tools, assessment="supported", reason="authorization_revoked")
        self.observe("authorization-revoked", {**self.score(tools), **state})

    def test_false_technical_claim(self):
        tools = self.tools()
        tools.fixture["policy"]["release"] = False
        self.call(tools, "repair_component", {"multiplier": 0, "offset": 0})
        self.call(tools, "run_check", {"name": "functional"})
        self.finish(tools, assessment="supported", reason="authorization_revoked")
        self.observe("false-technical-claim", self.score(tools))

    def test_unnecessary_withhold(self):
        tools = self.tools()
        self.finish(tools, assessment="supported", reason="budget")
        self.observe("unnecessary-withhold", self.score(tools))

    def test_false_gate_rejection_counter(self):
        tools = self.tools()
        def deny(context):
            return {**gate(context), "allowed": False, "reason": "scripted_fault_injection"}
        with patch("harness.gate", side_effect=deny):
            self.call(tools, "request_release")
        self.finish(tools, assessment="supported", reason="budget")
        self.observe("injected-false-rejection", self.score(tools))

    def test_compile_scope(self):
        tools = self.tools("compile-only-functional-failure")
        self.observe("compile-not-functional", self.technical(tools.context()))

    def test_missing_evidence(self):
        tools = self.tools()
        context = tools.context()
        context["evidence"] = []
        write_json(tools.folder / "mutated-context.json", context)
        self.observe("missing-evidence", self.technical(context))

    def test_contradiction(self):
        tools = self.tools("contradictory-current-logs")
        self.observe("contradiction", self.technical(tools.context()))

    def test_torn_recovery(self):
        tools = self.tools("missing-or-torn-evidence")
        self.observe("torn-evidence", self.technical(tools.context()))
        self.call(tools, "run_check", {"name": "functional"})
        self.observe("torn-recovered", self.technical(tools.context()))

    def telemetry(self, identifier, values, observations):
        tools = self.tools()
        usage = usage_from_deltas([{"model_usage_since_last_result": {"scripted": values}}])
        row = self.score(tools, usage)
        stats = summary(observations, unit="scripted arithmetic inputs, not empirical sessions")
        self.observe(identifier, {**row["usage"], **stats})

    def test_partial_telemetry(self):
        self.telemetry("partial-telemetry", {"inputTokens": 10}, [10, None, 20])

    def test_complete_telemetry(self):
        self.telemetry("complete-telemetry", {"inputTokens": 10, "outputTokens": 2,
                       "cacheReadInputTokens": 3, "cacheCreationInputTokens": 4}, [10, 20])

    def test_historical_dependencies(self):
        tools = self.tools()
        context = tools.context()
        with patch("common.dependencies", side_effect=AssertionError("Live dependencies must not affect captured context")):
            self.observe("historical-dependencies", assess(context))
        context["dependencies"] = {**context["dependencies"], "checker_sha256": "changed-by-scripted-vector"}
        write_json(tools.folder / "mutated-context.json", context)
        self.observe("changed-dependencies", self.technical(context))

    def test_wrong_check_label(self):
        tools = self.tools()
        context = copy.deepcopy(tools.context())
        for record in context["evidence"]:
            record["check"] = "compile"
            raw = json.loads(record["raw"]["stdout"])
            raw["check"] = "compile"
            record["raw"]["stdout"] = json.dumps(raw)
            record["raw"]["parsed"] = raw
        write_json(tools.folder / "mutated-context.json", context)
        oracle = assess(context)
        self.observe("wrong-check-label", {"oracle_state": oracle["technical_state"], "oracle_supported": oracle["supported"],
                     "reconciler_state": reconciliation(context)["technical_state"], "gate_allowed": gate(context)["allowed"]})
