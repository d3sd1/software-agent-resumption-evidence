#!/usr/bin/env python3
"""Generate vector workload figures and manuscript tables from retained results.

Only standard-library Python and an existing local LaTeX installation are used.
No model is called. No unavailable telemetry is replaced with a numeric zero.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
from pathlib import Path
import statistics
import subprocess

ROOT = Path(__file__).resolve().parent
ORDER = ("B0", "B1", "B2", "B3", "T", "G", "P")
BLUE = "2563eb"


def tex_escape(text: object) -> str:
    replacements = {"\\": r"\textbackslash{}", "_": r"\_", "%": r"\%", "&": r"\&", "#": r"\#", "{": r"\{", "}": r"\}"}
    return "".join(replacements.get(c, c) for c in str(text))


def numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def count(metrics: dict, name: str) -> int:
    value = metrics[name]["count"]
    if not isinstance(value, int):
        raise ValueError(f"Missing integer count for {name}")
    return value


def draw_workload(rows: list[dict], arms: list[str], out: Path, label: str) -> dict:
    width, height = 432, 270
    left, bottom, plot_width, plot_height = 48, 49, 366, 178
    values = [r["total_tokens"] for r in rows if numeric(r.get("total_tokens"))]
    if not values:
        raise ValueError("No observed token values; refusing to fabricate a chart")
    step = max(1000, math.ceil(max(values) * 1.08 / 5000) * 1000)
    ymax = 5 * step
    figure = [r"\documentclass[10pt]{article}", r"\usepackage[T1]{fontenc}", r"\usepackage{lmodern}",
              r"\usepackage{xcolor}", r"\usepackage[paperwidth=432bp,paperheight=270bp,margin=0bp]{geometry}",
              r"\pagestyle{empty}", r"\setlength{\parindent}{0pt}", r"\setlength{\unitlength}{1bp}",
              r"\definecolor{series}{HTML}{2563EB}", r"\definecolor{grid}{gray}{0.88}",
              r"\begin{document}", r"\noindent\begin{picture}(432,270)"]
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="576" height="360" viewBox="0 0 {width} {height}" role="img" aria-label="Recorded tokens per session by experimental arm">',
           '<rect width="432" height="270" fill="white"/>',
           '<g font-family="Latin Modern Roman,serif" font-size="10" fill="#111827">']

    def text(x: float, y: float, value: str, align: str = "middle") -> None:
        anchor = {"middle": "", "end": "r", "start": "l"}[align]
        figure.append(f"\\put({x:.2f},{y:.2f}){{\\makebox(0,0)[{anchor}]{{{tex_escape(value)}}}}}")
        svg.append(f'<text x="{x:.2f}" y="{height-y:.2f}" text-anchor="{align}" dominant-baseline="middle">{html.escape(value)}</text>')

    def line(x1: float, y1: float, x2: float, y2: float, color: str, thickness: float) -> None:
        if y1 != y2:
            raise ValueError("Only horizontal rules are needed for this figure")
        figure.append(f"\\put({x1:.2f},{y1:.2f}){{{{\\color{{{color}}}\\rule{{{x2-x1:.2f}bp}}{{{thickness:.2f}bp}}}}}}")
        stroke = "#e0e0e0" if color == "grid" else "#111827"
        svg.append(f'<line x1="{x1:.2f}" x2="{x2:.2f}" y1="{height-y1:.2f}" y2="{height-y2:.2f}" stroke="{stroke}" stroke-width="{thickness}"/>')

    text(width / 2, 252, "Recorded tokens per session")
    text(width / 2, 238, "Input + output + reported cache categories; not invoiced cost")
    for index in range(6):
        y = bottom + plot_height * index / 5
        line(left, y, left + plot_width, y, "grid", 0.35)
        text(left - 7, y, f"{index*step/1000:g}k", "end")
    observations = []
    for index, arm in enumerate(arms):
        x = left + plot_width * (index + 0.5) / len(arms)
        selected = sorted((r for r in rows if r["arm"] == arm and numeric(r.get("total_tokens"))), key=lambda r: r["id"])
        observed = [r["total_tokens"] for r in selected]
        for j, row in enumerate(selected):
            jitter = 0 if len(selected) == 1 else -8 + 16 * j / (len(selected)-1)
            y = bottom + plot_height * row["total_tokens"] / ymax
            xp = x + jitter
            figure.append(f"\\put({xp:.2f},{y:.2f}){{{{\\color{{white}}\\circle*{{8}}}}}}")
            figure.append(f"\\put({xp:.2f},{y:.2f}){{{{\\color{{series}}\\circle*{{6}}}}}}")
            detail = f'{row["id"]}: {row["total_tokens"]} reported tokens'
            svg.append(f'<circle cx="{xp:.2f}" cy="{height-y:.2f}" r="3" fill="#{BLUE}" stroke="white" stroke-width="1.5" tabindex="0" aria-label="{html.escape(detail,quote=True)}"><title>{html.escape(detail)}</title></circle>')
            observations.append({"run_id": row["id"], "arm": arm, "family": row["family"], "total_tokens": row["total_tokens"]})
        if observed:
            y = bottom + plot_height * statistics.median(observed) / ymax
            line(x - 10, y, x + 10, y, "black", 1.2)
        text(x, 35, arm)
        text(x, 22, f"n={len(observed)}")
    figure.append(r"\put(103,7){{\color{series}\circle*{6}}}")
    svg.append(f'<circle cx="103" cy="263" r="3" fill="#{BLUE}"/>')
    text(111, 7, "Session", "start")
    line(230, 7, 246, 7, "black", 1.2)
    text(253, 7, "Median", "start")
    figure.extend([r"\end{picture}", r"\end{document}"])
    svg.extend(["</g>", "</svg>"])
    stem = f"{label}-token-workload"
    (out / (stem + ".tex")).write_text("\n".join(figure) + "\n", encoding="utf-8")
    (out / (stem + ".svg")).write_text("\n".join(svg) + "\n", encoding="utf-8")
    result = subprocess.run(["pdflatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", stem + ".tex"], cwd=out, capture_output=True, text=True, timeout=120)
    (out / (stem + "-compile.txt")).write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Figure compilation failed; see {stem}-compile.txt")
    with (out / (stem + ".csv")).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["run_id", "arm", "family", "total_tokens"])
        writer.writeheader()
        writer.writerows(observations)
    return {"figure": stem, "observations": len(observations), "missing_token_rows": len(rows)-len(observations), "axis_max_tokens": ymax}


def write_tables(data: dict, arms: list[str], out: Path, label: str) -> None:
    outcome = [r"\begin{tabular}{@{}lrrrrrr@{}}", r"\toprule", r"Arm & Assigned & Correct & Delivered & Unsafe req. & Unsafe rel. & False block \\", r"\midrule"]
    workload = [r"\begin{tabular}{@{}lrrrr@{}}", r"\toprule", r"Arm & Checks & Operations & Tokens & Median time (s) \\", r"\midrule"]
    for arm in arms:
        metrics = data["by_arm"][arm]
        correct_key = "protocol_correct_disposition" if "protocol_correct_disposition" in metrics else "accepted_completion"
        blocked = metrics["false_block_positive"]
        block_text = f'{blocked["count"]}/{blocked["denominator"]}' if blocked["denominator"] else "---"
        outcome.append(f"{arm} & {metrics['assigned']} & {count(metrics,correct_key)} & {count(metrics,'supported_release')} & {count(metrics,'unsupported_attempted_release')} & {count(metrics,'unsupported_committed_release')} & {block_text} " + chr(92) * 2)
        selected = [r for r in data["per_run"] if r["arm"] == arm]
        tokens = [r.get("total_tokens") for r in selected]
        token_text = str(int(sum(tokens))) if all(numeric(t) for t in tokens) else "---"
        times = [r["wall_seconds"] for r in selected if numeric(r.get("wall_seconds"))]
        time_text = f"{statistics.median(times):.2f}" if times else "---"
        workload.append(f"{arm} & {metrics['checks']['sum']} & {metrics['executed_tools']['sum']} & {token_text} & {time_text} " + chr(92) * 2)
    for table in (outcome,workload):
        table.extend([r"\bottomrule", r"\end{tabular}"])
    (out / f"{label}-outcomes.tex").write_text("\n".join(outcome)+"\n", encoding="utf-8")
    (out / f"{label}-workload.tex").write_text("\n".join(workload)+"\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "results/pilot_results.json")
    parser.add_argument("--label", default="pilot")
    args = parser.parse_args()
    if not args.label.replace("-", "").isalnum():
        raise SystemExit("Label must be alphanumeric with optional hyphens")
    data = json.loads(args.results.read_text(encoding="utf-8"))
    if not isinstance(data.get("per_run"), list) or not isinstance(data.get("by_arm"), dict):
        raise SystemExit("Unsupported result schema; expected per_run and by_arm")
    # The expanded scorer nests telemetry to preserve its provenance. Normalize
    # only a derived view for rendering; do not alter the retained result file.
    normalized = []
    for source_row in data["per_run"]:
        row = dict(source_row)
        for key, group in (("total_tokens", "usage"), ("wall_seconds", "runtime")):
            nested = row.get(group, {})
            if key not in row:
                row[key] = nested.get(key)
            elif key in nested and row[key] != nested[key]:
                raise ValueError(f"Conflicting flat/nested telemetry for {row['id']}: {key}")
        normalized.append(row)
    data = {**data, "per_run": normalized}
    arms = [a for a in ORDER if a in data["by_arm"]]
    if set(data["by_arm"]) != set(arms):
        raise SystemExit("Unknown arms; explicitly update the plotting order")
    out = ROOT / "figures"
    out.mkdir(parents=True, exist_ok=True)
    metadata = draw_workload(data["per_run"], arms, out, args.label)
    write_tables(data, arms, out, args.label)
    groups = data.get("per_family_arm", [])
    if groups:
        family_order = list(dict.fromkeys(row["family"] for row in groups))
        family_codes = {name: f"F{i+1}" for i, name in enumerate(family_order)}
        lines = [r"\begin{longtable}{@{}llrrrr@{}}",
                 r"\caption{Within-family workload (mean $\pm$ sample standard deviation).}" + chr(92) + f"label{{tab:{args.label}-family-workload}}" + chr(92)*2,
                 r"\toprule",
                 "Family & Arm & $n$ & Checks & Tokens (k) & Time (s) " + chr(92)*2,
                 r"\midrule\endfirsthead", r"\toprule",
                 "Family & Arm & $n$ & Checks & Tokens (k) & Time (s) " + chr(92)*2,
                 r"\midrule\endhead", r"\bottomrule\endfoot"]
        csv_rows = []
        for family in family_order:
            for arm in arms:
                row = next(x for x in groups if x["family"] == family and x["arm"] == arm)
                fields = []
                for key, scale, precision in (("checks",1,2),("total_tokens",1000,3),("wall_seconds",1,2)):
                    metric = row[key]
                    if numeric(metric.get("mean")) and numeric(metric.get("std")):
                        fields.append(f"${metric['mean']/scale:.{precision}f}" + chr(92) + f"pm {metric['std']/scale:.{precision}f}$")
                    else:
                        fields.append("---")
                lines.append(f"{family_codes[family]} & {arm} & {row['assigned']} & " + " & ".join(fields) + " " + chr(92)*2)
                csv_rows.append({"family_code": family_codes[family], "family": family, "arm": arm, "n": row["assigned"],
                                 **{key+suffix: row[key].get(field) for key in ("checks","total_tokens","wall_seconds")
                                    for suffix,field in (("_mean","mean"),("_sd","std"),("_observed","n_observed"))}})
        lines.append(r"\end{longtable}")
        (out / f"{args.label}-family-workload.tex").write_text("\n".join(lines)+"\n",encoding="utf-8")
        with (out / f"{args.label}-family-workload.csv").open("w",newline="",encoding="utf-8") as handle:
            writer=csv.DictWriter(handle,fieldnames=list(csv_rows[0])); writer.writeheader();writer.writerows(csv_rows)
        (out / f"{args.label}-family-map.json").write_text(json.dumps(family_codes,indent=2)+"\n",encoding="utf-8")
    prefix = "".join(c for c in args.label.title() if c.isalpha())
    rows = data["per_run"]
    token_values = [r.get("total_tokens") for r in rows]
    values = {
        "Assigned": data["assigned"],
        "Families": len({r["family"] for r in rows}),
        "Arms": len(arms),
        "Completed": data["complete_structured"],
        "SupportedReleaseSessions": sum(count(m, "supported_release") for m in data["by_arm"].values()),
        "CorrectDispositions": sum(count(m, "protocol_correct_disposition" if "protocol_correct_disposition" in m else "accepted_completion") for m in data["by_arm"].values()),
        "Holds": sum((r.get("finish") or {}).get("status") == "hold" for r in rows),
        "UnsafeRuns": sum(count(m, "unsupported_committed_release") for m in data["by_arm"].values()),
        "UnsafeAttempts": sum(count(m, "unsupported_attempted_release") for m in data["by_arm"].values()),
        "Checks": sum(m["checks"]["sum"] for m in data["by_arm"].values()),
        "Tools": sum(m["executed_tools"]["sum"] for m in data["by_arm"].values()),
        "TotalTokens": int(sum(token_values)) if all(numeric(x) for x in token_values) else "not fully observed",
    }
    macros = ["% Generated from retained results; do not edit by hand."]
    for name, value in values.items():
        macros.append(chr(92) + "providecommand{" + chr(92) + prefix + name + "}{" + str(value) + "}")
    (out / f"{args.label}-values.tex").write_text("\n".join(macros)+"\n", encoding="utf-8")
    metadata["generated_values"] = values
    metadata.update({"input": str(args.results.relative_to(ROOT)) if args.results.is_relative_to(ROOT) else args.results.name,
                     "input_sha256": hashlib.sha256(args.results.read_bytes()).hexdigest(),
                     "palette": ["#2563eb"], "font": "Latin Modern 10pt",
                     "interpretation": "Descriptive workload distribution; no efficiency significance or billing inference"})
    (out / f"{args.label}-assets.json").write_text(json.dumps(metadata,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(metadata,indent=2))


if __name__ == "__main__":
    main()
