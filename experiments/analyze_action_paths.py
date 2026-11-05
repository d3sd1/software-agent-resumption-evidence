#!/usr/bin/env python3
"""Post-hoc descriptive analysis of every retained expansion tool trace.

Requested during simulated review. No model calls, tuning, causal inference, or
changes to frozen inputs/records. All assigned expanded runs are included.
"""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARMS = ("B0", "B1", "B2", "B3", "T", "G", "P")


def main():
    source = ROOT / "results/expanded_results.json"
    data = json.loads(source.read_text())
    rows, patterns, examples = [], Counter(), []
    for run in data["per_run"]:
        if not run["launched"]:
            raise RuntimeError("This complete-run analysis refuses silently excluding unlaunched cells")
        directory = (ROOT / "expansion" / run["events_path"]).parent.resolve()
        if not directory.is_relative_to(ROOT / "expansion"):
            raise RuntimeError("Trace path escapes expansion directory")
        path = directory / "tool-events.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        calls = [e for e in events if e.get("type") == "tool_result" and e.get("executed")]
        if len(calls) != run["executed_tools"]:
            raise RuntimeError("Tool count differs from retained score: " + run["id"])
        checked = [i for i,e in enumerate(calls) if e["name"] == "run_check" and e["arguments"].get("name") == "functional"]
        changes = [i for i,e in enumerate(calls) if e["name"] == "repair_component" and e["result"].get("changed_bytes") is True]
        tokens = [e["name"] + (":" + str(e["arguments"].get("name")) if e["name"] in ("run_check", "read_file") else "") for e in calls]
        sequence = " / ".join(tokens)
        patterns[(run["family"],run["arm"],sequence)] += 1
        row = {"id":run["id"],"family":run["family"],"arm":run["arm"],"seed":run["fixture_order_seed"],
               "inspect_calls":sum(e["name"] == "inspect_state" for e in calls),
               "read_calls":sum(e["name"] == "read_file" for e in calls),
               "functional_checks":len(checked),"changed_repairs":len(changes),
               "repair_before_first_check":bool(changes and checked and min(changes)<min(checked)),
               "supported_delivery_without_new_functional_check":bool(run["supported_delivery"] and not checked),
               "tool_errors":sum(bool(e.get("is_error")) for e in calls),"sequence":sequence,
               "trace_sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
        rows.append(row)
        if run["family"] == "untracked-config-drift" and run["arm"] == "B1" and run["fixture_order_seed"] == 42:
            examples.append({"selection_rule":"F3 / B1 / fixture-order seed 42; illustrative, not a causal or representative estimate",
                             "row":row,"events":calls})
    summary=[]
    for arm in ARMS:
        subset=[r for r in rows if r["arm"]==arm]
        summary.append({"arm":arm,"runs":len(subset),"runs_with_inspection":sum(r["inspect_calls"]>0 for r in subset),
                        "read_calls":sum(r["read_calls"] for r in subset),
                        "runs_repair_before_check":sum(r["repair_before_first_check"] for r in subset),
                        "supported_reuse_runs":sum(r["supported_delivery_without_new_functional_check"] for r in subset),
                        "functional_checks":sum(r["functional_checks"] for r in subset),
                        "tool_errors":sum(r["tool_errors"] for r in subset)})
    result={"analysis_status":"post-hoc descriptive trace analysis requested during review",
            "model_calls":0,"source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
            "run_count":len(rows),"summary":summary,"per_run":rows,
            "patterns":[{"family":k[0],"arm":k[1],"sequence":k[2],"count":v} for k,v in sorted(patterns.items())],
            "worked_examples":examples,"limits":"Actions are observed; reasons or causal effects are not inferred. Reuse means supported delivery without a new functional check in that session."}
    (ROOT/"results/action_path_analysis.json").write_text(json.dumps(result,indent=2)+"\n")
    with (ROOT/"results/action_paths.csv").open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    table=[r"\begin{tabular}{@{}lrrrrr@{}}",r"\toprule",
           "Arm & Inspected & File reads & Repair-first & Reuse & Tool errors "+chr(92)*2,r"\midrule"]
    for r in summary:
        table.append(f"{r['arm']} & {r['runs_with_inspection']} & {r['read_calls']} & {r['runs_repair_before_check']} & {r['supported_reuse_runs']} & {r['tool_errors']} "+chr(92)*2)
    table += [r"\bottomrule",r"\end{tabular}"]
    (ROOT/"figures/expanded-action-paths.tex").write_text("\n".join(table)+"\n")
    print(json.dumps({"run_count":len(rows),"summary":summary,"example":examples[0]['row'] if examples else None},indent=2))


if __name__ == "__main__":
    main()
