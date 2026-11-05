"""Format unchanged cohort observations for the revised manuscript.

This post-archive presentation helper does not change any endpoint or execute
participants. Variation is descriptive across order-paired complete blocks.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("recorded_access_assets", HERE / "generate_assets.py")
ASSETS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ASSETS)
END = chr(92) * 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, default=ASSETS.SOURCE)
    parser.add_argument("--output", type=Path, default=HERE / "publication-assets")
    args = parser.parse_args()
    raw = args.evaluation.read_bytes()
    data = json.loads(raw)
    if len(data["rows"]) != 160 or data["flow"]["completion_known"] != 160:
        raise ValueError("Expected the complete recorded cohort; no missing-data imputation")
    workload = [r"\begin{tabular}{@{}lrrrr@{}}", r"\toprule",
                "Condition & Success & " + r"\shortstack{Retrieval\\calls/run}" + " & Message kB & Auto kB " + END, r"\midrule"]
    for arm, regime in ASSETS.CONDITIONS:
        rows = [r for r in data["rows"] if r["cell"]["arm"] == arm and r["cell"]["regime"] == regime]
        if len(rows) != 40 or any(type(r["success"]) is not bool for r in rows):
            raise ValueError("Incomplete or unknown condition")
        message = ASSETS.stats(rows, "study_supplied_message_bytes")["mean"]
        automatic = ASSETS.stats(rows, "automatic_bytes")["mean"]
        calls = ASSETS.stats(rows, "retrieval_calls")["mean"]
        workload.append(f"{arm} / {regime} & {sum(r['success'] for r in rows)}/40 & {calls:.0f} & {message/1000:.3f} & {automatic/1000:.3f} " + END)
    workload += [r"\bottomrule", r"\end{tabular}"]
    contrast = next(c for c in data["contrasts"] if c["metric"] == "study_supplied_message_bytes")
    table = [r"\begin{tabular}{@{}llrrr@{}}", r"\toprule",
             r"Case & State & $\Delta_G$ (B) & $\Delta_P$ (B) & Interaction (B) " + END, r"\midrule"]
    records = []
    for index, case in enumerate(ASSETS.CASE_ORDER, 1):
        for state in ("R", "U"):
            blocks = [b for b in contrast["secondary_complete_blocks"] if b["case"] == case and b["state"] == state]
            if len(blocks) != 5:
                raise ValueError("Incomplete paired scheduling block")
            cells = []
            for metric in ("delta_G", "delta_P", "interaction"):
                values = [b[metric] for b in blocks]
                mean, sd = statistics.mean(values), statistics.stdev(values)
                cells.append(f"${mean:.1f} \\pm {sd:.1f}$")
                records.append({"case": case, "state": state, "metric": metric, "n": 5, "mean": mean, "sample_std": sd})
            table.append(f"C{index} & {state} & " + " & ".join(cells) + " " + END)
    table += [r"\bottomrule", r"\end{tabular}"]
    descriptions = {
        "packaging-sibling-errors": "Collect later-sibling dependency errors while retaining the diamond-case control.",
        "itertools-large-range": "Equality and hashing of ranges beyond the platform-sized length limit.",
        "itertools-peekable-slice": "Reverse slicing retains bounded iterator consumption and cache behavior.",
        "dotenv-backslashes": "Set/get file round trips preserve quoted and backslash-containing values.",
    }
    cases_root = args.evaluation.resolve().parents[2] / "capsules/cohort-001/prepared/cases"
    case_table = [r"\begin{tabularx}{\linewidth}{@{}lp{0.24\linewidth}p{0.20\linewidth}X@{}}", r"\toprule",
                  "Case & Executable subject & Before / after & Focused acceptance " + END, r"\midrule"]
    for index, case in enumerate(ASSETS.CASE_ORDER, 1):
        info = json.loads((cases_root / case / "case.json").read_text())
        origin = info["provenance"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", origin["repo"]):
            raise ValueError("Unexpected repository identifier")
        packages = {name.split("/")[1] for name in info["snapshots"]["after"] if name.startswith("source/")}
        if len(packages) != 1:
            raise ValueError("Expected one declared package scope")
        package = packages.pop()
        links = []
        for version in ("before", "after"):
            commit = origin[version]
            if not re.fullmatch(r"[0-9a-f]{40}", commit):
                raise ValueError("Commit must be an exact full identifier")
            links.append("\\href{https://github.com/" + origin["repo"] + "/commit/" + commit + "}{\\texttt{" + commit[:12] + "}}")
        pair = "\\shortstack[l]{" + (chr(92) * 2).join(links) + "}"
        case_table.append(f"C{index} & " + "\\path{source/" + package + "/}" + " & " + pair + " & " + descriptions[case] + " " + END)
    case_table += [r"\bottomrule", r"\end{tabularx}"]
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "access-workload.tex").write_text("\n".join(workload) + "\n")
    (args.output / "access-contrasts-bytes.tex").write_text("\n".join(table) + "\n")
    (args.output / "access-case-contracts.tex").write_text("\n".join(case_table) + "\n")
    with (args.output / "access-contrasts-bytes.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0])); writer.writeheader(); writer.writerows(records)
    receipt = {"source_sha256": hashlib.sha256(raw).hexdigest(), "model_calls": 0,
               "source_unchanged": args.evaluation.read_bytes() == raw,
               "scope": "Presentation only; original unnormalized primary contrasts, five order-paired blocks per case/state; not matched provider randomness or population CI",
               "outputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.output.iterdir())}}
    (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"case_state_rows": 8, "cohort_sessions": 160, "source_unchanged": receipt["source_unchanged"], "model_calls": 0}))


if __name__ == "__main__":
    main()
