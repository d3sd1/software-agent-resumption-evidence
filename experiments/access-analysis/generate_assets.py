"""Generate descriptive tables/CSVs from the completed, frozen access cohort.

No participants, changes to source observations, significance tests, or pooling
with earlier phases. Small byte-level variation is retained in the CSV/JSON.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
EXPERIMENTS = HERE.parent
SOURCE = EXPERIMENTS / "access-study/collections/cohort-001/evaluation.json"
CASE_ORDER = ["packaging-sibling-errors", "itertools-large-range", "itertools-peekable-slice", "dotenv-backslashes"]
CONDITIONS = [("G", "bundled"), ("G", "distributed"), ("P", "bundled"), ("P", "distributed")]
METRICS = ["study_supplied_message_bytes", "automatic_bytes", "context_payload_bytes", "unique_document_bytes",
           "retrieval_calls", "checks", "input_tokens", "output_tokens", "cache_read_input_tokens",
           "cache_creation_input_tokens", "wall_seconds"]
END = chr(92) * 2


def stats(rows, key):
    values = [row[key] for row in rows]
    if any(type(v) not in (int, float) for v in values):
        raise ValueError("Unknown/non-numeric value must not become zero: " + key)
    return {"n": len(values), "sum": sum(values), "mean": statistics.mean(values),
            "sample_std": statistics.stdev(values) if len(values) > 1 else None}


def write_text(path, text):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=HERE / "assets")
    args = parser.parse_args()
    raw = args.source.read_bytes()
    data = json.loads(raw)
    rows = data["rows"]
    if len(rows) != 160 or data["flow"]["known_started"] != 160 or data["flow"]["workload_known"] != 160:
        raise ValueError("This completed-cohort presentation requires all 160 auditable rows")
    if any(type(row["success"]) is not bool for row in rows):
        raise ValueError("Unknown completion requires a missingness presentation")
    groups = []
    for arm, regime in CONDITIONS:
        chosen = [r for r in rows if r["cell"]["arm"] == arm and r["cell"]["regime"] == regime]
        if len(chosen) != 40:
            raise ValueError("Unbalanced completed condition")
        groups.append({"arm": arm, "regime": regime, "n": len(chosen),
                       "supported_completions": sum(r["success"] is True for r in chosen),
                       "unsupported_requests": sum(r["unsupported_request"] is True for r in chosen),
                       "unsupported_commits": sum(r["unsupported_commit"] is True for r in chosen),
                       "metrics": {key: stats(chosen, key) for key in METRICS}})
    cells = []
    for index, case in enumerate(CASE_ORDER, 1):
        for state in ("R", "U"):
            for arm, regime in CONDITIONS:
                chosen = [r for r in rows if r["cell"]["case"] == case and r["cell"]["state"] == state
                          and r["cell"]["arm"] == arm and r["cell"]["regime"] == regime]
                if len(chosen) != 5:
                    raise ValueError("Incomplete case/state/condition")
                cells.append({"case": case, "case_label": "C" + str(index), "state": state,
                              "arm": arm, "regime": regime, "metrics": {key: stats(chosen, key) for key in METRICS}})
    contrasts = [{"metric": item["metric"], **item["equal_case_state_aggregate"]}
                 for item in data["contrasts"]]
    args.output.mkdir(parents=True, exist_ok=False)
    result = {"source_sha256": hashlib.sha256(raw).hexdigest(), "source": str(args.source.relative_to(EXPERIMENTS)),
              "cohort_sessions": len(rows), "model_calls": 0, "flow": data["flow"],
              "groups": groups, "case_state_cells": cells, "contrasts": contrasts,
              "limits": "Finite-suite means; group SD mixes cases, within-cell SD describes five order-labelled fresh sessions; no population CI or efficiency inference"}
    write_text(args.output / "access-results.json", json.dumps(result, indent=2) + "\n")
    with (args.output / "access-case-workload.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["case", "state", "arm", "regime", "metric", "n", "sum", "mean", "sample_std"])
        writer.writeheader()
        for cell in cells:
            for metric, values in cell["metrics"].items():
                writer.writerow({**{k: cell[k] for k in ("case", "state", "arm", "regime")}, "metric": metric, **values})
    lines = [r"\begin{tabular}{@{}lrrrr@{}}", r"\toprule",
             "Condition & Success & Reads/run & Message kB & Auto kB " + END, r"\midrule"]
    for group in groups:
        m = group["metrics"]
        lines.append(f"{group['arm']} / {group['regime']} & {group['supported_completions']}/{group['n']} & "
                     f"{m['retrieval_calls']['mean']:.0f} & {m['study_supplied_message_bytes']['mean']/1000:.3f} & "
                     f"{m['automatic_bytes']['mean']/1000:.3f} " + END)
    lines += [r"\bottomrule", r"\end{tabular}"]
    write_text(args.output / "access-workload.tex", "\n".join(lines) + "\n")
    lines = [r"\begin{tabular}{@{}llrrrr@{}}", r"\toprule",
             "Case & State & G/B & G/D & P/B & P/D " + END, r"\midrule"]
    for case in CASE_ORDER:
        for state in ("R", "U"):
            selected = [c for c in cells if c["case"] == case and c["state"] == state]
            formatted = []
            for cell in selected:
                values = cell["metrics"]["study_supplied_message_bytes"]
                formatted.append(f"${values['mean']/1000:.3f} \\pm {values['sample_std']/1000:.3f}$")
            lines.append(selected[0]["case_label"] + " & " + state + " & " + " & ".join(formatted) + " " + END)
    lines += [r"\bottomrule", r"\end{tabular}"]
    write_text(args.output / "access-case-workload.tex", "\n".join(lines) + "\n")
    report = {"source_sha256": result["source_sha256"], "assigned": len(rows),
              "outputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.output.iterdir())},
              "source_unchanged": args.source.read_bytes() == raw, "model_calls": 0}
    write_text(args.output / "generation-receipt.json", json.dumps(report, indent=2) + "\n")
    print(json.dumps({"rows": len(rows), "case_state_condition_cells": len(cells), "output": str(args.output), "model_calls": 0}))


if __name__ == "__main__":
    main()
