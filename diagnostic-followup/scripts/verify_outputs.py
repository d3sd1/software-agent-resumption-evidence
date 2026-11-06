"""Read-only verification of follow-up outputs; no scorer/harness/model imports."""
import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    output = args.receipt.resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError("Receipt outside allowed follow-up directory")
    results = args.results.resolve()
    checks = []
    def require(name, condition):
        checks.append({"check": name, "passed": bool(condition)})
    summary = read(results / "summary.json")
    before, after = read(results / "inputs-before.json"), read(results / "inputs-after.json")
    pre = read(results / "pre-execution.json")
    require("Original input inventories exactly equal", before == after and len(before) == summary["input_files_checked"])
    for field, name in (("plan_sha256", "plan.json"), ("expectations_sha256", "expectations.json")):
        require("Pre-execution " + name + " hash unchanged", pre[field] == hashlib.sha256((ROOT / name).read_bytes()).hexdigest())
    require("Executed script hash current", pre["script_sha256"] == hashlib.sha256((ROOT / "scripts/run_followup.py").read_bytes()).hexdigest())
    require("No expectation mismatches", summary["expectation_mismatches"] == [])
    require("No model calls or old-control rerun", summary["model_calls"] == 0 and summary["historical_controls_rerun"] is False)
    controls = read(results / "retained-C-controls.json")["rows"]
    require("96 separately labelled retained controls", len(controls) == 96 and all(row["byte_mode"] == ["reference_render_only_not_participant"] for row in controls))
    require("Restore counts extracted from original response ledger", all(row["restores"] in (0, 1) and "Observed" in row["restore_count_basis"] for row in controls))
    recipients = read(results / "C-recipient-generic-views.json")
    require("160 unique preserved recipient records", len(recipients) == len({row["opaque_id"] for row in recipients}) == 160)
    require("160 indicator agreements, not identical observation views", all(row["three_positive_indicators_agree"] for row in recipients))
    witnesses = read(results / "information-witnesses.json")
    require("32 witnesses are separate and safe at observed boundaries", len(witnesses) == 32 and all(row["success"] and row["unsupported_requests"] == row["unsupported_commits"] == row["checks"] == 0 and row["not_a_recipient"] for row in witnesses))
    require("All witnesses inspect authority and preservation", all(row["proof"]["authorization_from_contract"] and row["proof"]["protection_from_contract_and_workspace"] for row in witnesses))
    pairs = read(results / "retained-control-pair-comparisons.json")
    expected = read(ROOT / "expectations.json")["retained_control_pairs"]
    require("Three controlled-view pair predictions retained", len(pairs) == 3 and all(all(p["observed"][k] == e[k] for k in ("final_only_equal", "commit_only_equal", "full_event_equal")) for p, e in zip(pairs, expected)))
    tree = ast.parse((ROOT / "scripts/run_followup.py").read_text())
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ("information_policy", "exposed_record_valid")]
    forbidden = {"oracle", "gate", "Harness", "ROOT", "DRAFT", "Path", "read", "open", "cfg", "prepared"}
    used = {node.id for function in functions for node in ast.walk(function) if isinstance(node, ast.Name)}
    require("Witness decision functions do not access hidden runtime/fixture/scorer APIs", len(functions) == 2 and not (used & forbidden))
    for name, expected_rows in (("retained-C-controls.csv", 96), ("information-witnesses.csv", 32), ("C-recipient-generic-views.csv", 160), ("C-composite-semantics.csv", 24)):
        with (results / name).open() as stream:
            require("CSV row count " + name, len(list(csv.DictReader(stream))) == expected_rows)
    receipt = {"kind": "independent_output_consistency_checks_not_new_experiments", "checks": checks,
               "passed": all(item["passed"] for item in checks), "model_calls": 0}
    with output.open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"checks": len(checks), "passed": receipt["passed"], "model_calls": 0}))
    if not receipt["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
