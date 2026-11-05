"""Boundary/integrity tests without model calls. All temporary files stay in experiments."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from common import ROOT, digest, read_json, source
from controls import gate, reconcile
from evaluate import oracle, semantic_truth
from harness import FixtureTools, prepare_run, render_prompt


class BoundaryTests(unittest.TestCase):
    def test_bridge_is_strict_and_sums_explicit_deltas(self):
        from cli_bridge import parse_action, usage_from_deltas
        allowed = ["inspect_state"]
        self.assertEqual(parse_action('{"tool":"inspect_state","arguments":{}}', allowed)["tool"], "inspect_state")
        for text in ['{"tool":"Bash","arguments":{}}', '[{"tool":"inspect_state","arguments":{}}]',
                     '{"tool":"inspect_state","arguments":{},"override":true}', 'not json']:
            with self.assertRaises(ValueError):
                parse_action(text, allowed)
        delta = {"model_usage_since_last_result": {"model": {"inputTokens": 10, "outputTokens": 3}}}
        self.assertEqual(usage_from_deltas([delta, delta])["input_tokens"], 20)
        self.assertIsNone(usage_from_deltas([{}]))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="test-", dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def tools(self, family="unchanged-valid", arm="B1", suffix="run"):
        prepare_run(self.root / suffix, family, arm)
        return FixtureTools(self.root / suffix)

    def release_context(self, tools):
        records = [json.loads(x) for x in (tools.folder / "release-events.jsonl").read_text().splitlines()]
        return records[0]["context"]

    def test_actual_check_and_repair(self):
        tools = self.tools("relevant-dirty-change", "P")
        result, error = tools.call("run_check", {"name": "functional-real"})
        self.assertFalse(error)
        self.assertEqual(result["evidence"]["outcome"], "fail")
        self.assertEqual(result["evidence"]["raw"]["exit_code"], 1)
        rec = reconcile(digest(tools.candidate.read_bytes()), tools.fixture["contract"], tools.fixture["dependencies"], tools.state["evidence"])
        self.assertEqual(rec["technical_state"], "contradicted")
        tools.call("repair_discount", {"multiplier": 90})
        result, _ = tools.call("run_check", {"name": "functional-real"})
        self.assertEqual(result["evidence"]["outcome"], "pass")
        result, _ = tools.call("request_release", {})
        self.assertTrue(result["committed"])
        self.assertTrue(oracle(self.release_context(tools))["supported"])

    def test_dirty_is_stale_not_contradicted(self):
        tools = self.tools("relevant-dirty-change")
        rec = reconcile(digest(tools.candidate.read_bytes()), tools.fixture["contract"], tools.fixture["dependencies"], tools.state["evidence"])
        self.assertEqual(rec["technical_state"], "stale")
        self.assertIsNone(rec["served_pass"])
        self.assertNotEqual(tools.candidate.read_bytes(), source().encode())

    def test_mock_and_unavailable_are_not_pass(self):
        tools = self.tools("mock-only", "G")
        result, error = tools.call("run_check", {"name": "functional-real"})
        self.assertFalse(error)
        self.assertEqual(result["evidence"]["outcome"], "unknown")
        self.assertEqual(result["evidence"]["raw"]["exit_code"], 3)
        result, _ = tools.call("request_release", {})
        self.assertFalse(result["committed"])
        self.assertEqual(result["gate"]["technical"]["technical_state"], "unknown")
        self.assertFalse(oracle(self.release_context(tools))["supported"])

    def test_revocation_preserves_technical_pass(self):
        tools = self.tools("authorization-revoked", "P")
        result, _ = tools.call("request_release", {})
        self.assertFalse(result["committed"])
        self.assertEqual(result["gate"]["technical"]["technical_state"], "supported")
        self.assertEqual(oracle(self.release_context(tools))["reasons"], ["authorization_revoked"])

    def test_shared_gate_g_p_all_families(self):
        for family in read_json(ROOT / "config.json")["families"]:
            outcomes = []
            for arm in ["G", "P"]:
                tools = self.tools(family, arm, family + arm)
                response, _ = tools.call("request_release", {})
                expected = oracle(self.release_context(tools))["supported"]
                self.assertEqual(response["committed"], expected)
                outcomes.append(response["committed"])
            self.assertEqual(outcomes[0], outcomes[1])

    def test_unsupported_commit_survives_later_hold_and_edit(self):
        tools = self.tools("relevant-dirty-change", "B1")
        initial = tools.candidate.read_bytes()
        response, _ = tools.call("request_release", {})
        self.assertTrue(response["committed"])
        context = self.release_context(tools)
        self.assertFalse(oracle(context)["supported"])
        tools.call("repair_discount", {"multiplier": 90})
        tools.call("finish", {"status": "hold", "assessment": "stale", "reason": "technical_failure"})
        released = list((tools.folder / "release_sink").iterdir())
        self.assertEqual(len(released), 1)
        self.assertEqual(released[0].read_bytes(), initial)
        self.assertEqual(digest(initial), context["candidate_sha256"])

    def test_no_paths_code_or_evidence_injection(self):
        tools = self.tools()
        before = tools.candidate.read_bytes()
        for name, args in [("read_file", {"name": "../../config.json"}),
                           ("read_file", {"name": "/etc/passwd"}),
                           ("repair_discount", {"multiplier": "90; import os"}),
                           ("repair_discount", {"multiplier": True}),
                           ("request_release", {"policy": {"release": True}}),
                           ("run_check", {"name": "bash"}), ("Bash", {"command": "pwd"})]:
            result, error = tools.call(name, args)
            self.assertTrue(error, result)
        self.assertEqual(before, tools.candidate.read_bytes())
        self.assertFalse((tools.folder / "release-events.jsonl").exists())

    def test_tool_cap(self):
        tools = self.tools()
        for _ in range(8):
            tools.call("inspect_state", {})
        _, error = tools.call("request_release", {})
        self.assertTrue(error)
        self.assertEqual(tools.state["executed_tools"], 8)
        self.assertFalse((tools.folder / "release-events.jsonl").exists())

    def test_missing_provenance_oracle_rejects(self):
        tools = self.tools()
        tools.call("request_release", {})
        context = self.release_context(tools)
        context["evidence"][0]["raw"]["stdout"] = "unavailable"
        self.assertFalse(oracle(context)["supported"])

    def test_conflict_and_dependency_changes(self):
        tools = self.tools()
        tools.call("request_release", {})
        context = self.release_context(tools)
        failure = copy.deepcopy(context["evidence"][0])
        failure["id"] = "conflicting-failure"
        failure["outcome"] = "fail"
        failure["raw"]["exit_code"] = 1
        failure["raw"]["parsed"]["outcome"] = "fail"
        failure["raw"]["stdout"] = json.dumps(failure["raw"]["parsed"])
        context["evidence"].append(failure)
        self.assertFalse(oracle(context)["supported"])
        self.assertFalse(gate(context["candidate_sha256"], context["contract"], context["dependencies"], context["evidence"], context["policy"])["allowed"])
        context["evidence"].pop()
        context["dependencies"] = {"checker_sha256": "changed", "python": "changed"}
        self.assertFalse(oracle(context)["supported"])
        self.assertFalse(gate(context["candidate_sha256"], context["contract"], context["dependencies"], context["evidence"], context["policy"])["allowed"])

    def test_gate_uses_current_policy_at_operation(self):
        tools = self.tools(arm="G")
        tools.fixture["policy"]["release"] = False
        result, _ = tools.call("request_release", {})
        self.assertFalse(result["committed"])
        self.assertEqual(result["gate"]["reason"], "authorization_revoked")

    def test_common_task_and_b1_g_handoff_equal(self):
        payload = {}
        for arm in read_json(ROOT / "config.json")["arms"]:
            tools = self.tools(arm=arm, suffix=arm)
            first_render = render_prompt(tools.state)[0]
            self.assertEqual(first_render, render_prompt(tools.state)[0])
            payload[arm] = json.loads(first_render)
        self.assertEqual(payload["B1"]["handoff"], payload["G"]["handoff"])
        self.assertEqual(payload["B3"]["handoff"], payload["P"]["handoff"])
        self.assertIsNone(payload["B0"]["handoff"])
        self.assertNotIn("evidence_links", payload["B2"]["handoff"])
        tasks = [p["current_task"] for p in payload.values()]
        for task in tasks:
            task.pop("gate_enforced")
        self.assertTrue(all(task == tasks[0] for task in tasks))

    def test_mcp_stdio_protocol(self):
        tools = self.tools()
        requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "inspect_state", "arguments": {}}}]
        response = subprocess.run([sys.executable, str(ROOT / "mcp_server.py"), "--run-dir", str(tools.folder)],
                    input="".join(json.dumps(x) + "\n" for x in requests), text=True, capture_output=True, timeout=10)
        self.assertEqual(response.returncode, 0, response.stderr)
        decoded = [json.loads(x) for x in response.stdout.splitlines()]
        self.assertEqual(len(decoded), 3)
        self.assertEqual(len(decoded[1]["result"]["tools"]), 6)
        self.assertNotIn("Bash", str(decoded[1]))

    def test_semantic_oracle(self):
        self.assertTrue(semantic_truth(source(90)))
        self.assertFalse(semantic_truth(source(80)))
        self.assertFalse(semantic_truth("import os\n"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
