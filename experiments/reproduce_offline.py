#!/usr/bin/env python3
"""Reproduce retained analyses and publication assets without any model calls."""
from pathlib import Path
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent


def run(arguments):
    subprocess.run([sys.executable, *arguments], cwd=ROOT, check=True)


def validate_phase_summary(summary, pilot, expansion):
    """Reject a stale derived phase ledger without pooling the experiments."""
    if summary.get("phases_are_not_pooled") is not True:
        raise RuntimeError("Phase summary does not preserve phase separation")
    for phase, source in (("pilot", pilot), ("expansion", expansion)):
        for field in ("assigned", "launched", "complete_structured", "by_arm"):
            if summary[phase][field] != source[field]:
                raise RuntimeError("Stale phase summary: " + phase + "." + field)
    for field in ("action_exposed", "per_family_arm", "deterministic_reference"):
        if summary["expansion"][field] != expansion[field]:
            raise RuntimeError("Stale phase summary: expansion." + field)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-pdfs", action="store_true", help="Also compile both manuscripts and the supplement locally")
    args = parser.parse_args()
    original = json.loads((ROOT / "results/expanded_results.json").read_text())
    run([str(ROOT / "expansion/run_all.py"), "--verify-freeze"])
    run([str(ROOT / "evaluate.py")])
    run([str(ROOT / "expansion/run_all.py"), "--evaluate-only"])
    recreated = json.loads((ROOT / "results/expanded_results.json").read_text())
    compared = ["assigned", "launched", "action_exposed", "complete_structured", "by_arm", "per_family_arm", "per_run"]
    for field in compared:
        if original[field] != recreated[field]:
            raise SystemExit("Reanalysis changed retained scientific results: " + field)
    run([str(ROOT / "aggregate_phases.py")])
    pilot = json.loads((ROOT / "results/pilot_reanalysis.json").read_text())
    summary = json.loads((ROOT / "results/aggregated_results.json").read_text())
    validate_phase_summary(summary, pilot, recreated)
    run(["-I", str(ROOT / "analyze_action_paths.py")])
    run(["-I", str(ROOT / "generate_figures.py"), "--label", "pilot"])
    run(["-I", str(ROOT / "generate_figures.py"), "--results", str(ROOT / "results/expanded_results.json"), "--label", "expanded"])
    if args.with_pdfs:
        run(["-I", str(ROOT.parent / "build.py")])
        for _ in range(2):
            subprocess.run(["pdflatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "supplement.tex"], cwd=ROOT.parent, check=True)
    receipt = {"completed_at": datetime.now(timezone.utc).isoformat(), "model_calls": 0,
               "scientific_result_fields_unchanged": compared, "phase_summary_rebuilt_and_verified": True,
               "figures_regenerated": True,
               "manuscript_pdfs_rebuilt": args.with_pdfs,
               "limits": "Reanalysis of retained observations, not new participant execution or submission approval; PDF metadata dates may differ"}
    (ROOT / "results/offline_reproduction_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
