#!/usr/bin/env python3
"""Audit public cohort-001 message bytes using only the extracted public package.

Standard library only; no study imports, original streams, model calls or network.
--cohort accepts the extracted package root or its collections/cohort-001 directory.
--output must be a new file outside the input package. Optional --self-test alters
one same-length content character in a temporary copy of the consumed public files.
The preserved evaluation is consulted only after independent reconstruction.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import sys
import tempfile


COHORT = Path("experiments/access-study/collections/cohort-001")
CONFIG = Path("experiments/access-study/config.json")


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def fraction(value):
    value = Fraction(value)
    return {"exact": str(value), "decimal": float(value)}


class Auditor:
    def __init__(self, root):
        self.root = root
        self.errors = []
        self.checks = 0
        self.inputs = {}
        manifest_bytes = self.raw("export-manifest.json")
        self.manifest = json.loads(manifest_bytes)
        self.entries = {row["path"]: row for row in self.manifest["files"]}
        self.require(len(self.entries) == len(self.manifest["files"]), "unique_export_inventory_paths")
        self.manifest_sha256 = digest(manifest_bytes)

    def require(self, condition, code, location=None):
        self.checks += 1
        if not condition:
            self.errors.append({"code": code, "location": location})

    def raw(self, name):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Non-relative package input path")
        path = self.root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("Linked or escaped package input")
        data = path.read_bytes()
        key = relative.as_posix()
        self.inputs[key] = {"bytes": len(data), "sha256": digest(data)}
        if hasattr(self, "entries"):
            entry = self.entries.get(key)
            self.require(entry is not None, "input_listed_in_public_inventory", key)
            if entry is not None:
                self.require(entry.get("export_sha256") == digest(data), "public_file_sha256", key)
                if "export_bytes" in entry:
                    self.require(entry["export_bytes"] == len(data), "public_file_size", key)
        return data

    def obj(self, name):
        return json.loads(self.raw(name))

    def session(self, cell):
        identifier = cell["opaque_id"]
        if not isinstance(identifier, str) or Path(identifier).name != identifier or identifier in (".", ".."):
            raise ValueError("Invalid assignment identifier")
        base = COHORT / "sessions" / identifier
        start_raw = self.raw(base / "slot-start.json")
        session_raw = self.raw(base / "session.json")
        end = self.obj(base / "slot-end.json")
        start, session = json.loads(start_raw), json.loads(session_raw)
        self.require(start["cell"] == session["cell"] == cell, "public_lifecycle_cell", identifier)
        self.require(session["slot_start_sha256"] == end["slot_start_sha256"] == digest(start_raw), "public_start_binding", identifier)
        self.require(end["session_sha256"] == digest(session_raw), "public_session_binding", identifier)
        closure = session["message_closure"]
        self.require(closure == session["transport"]["message_closure"], "public_closure_copies", identifier)
        self.require(closure.get("schema") == "message-ledger-closure-v1" and closure.get("closed") is True, "closed_public_message_ledger", identifier)
        raw = self.raw(base / "message-ledger.jsonl")
        self.require(raw.endswith(b"\n"), "terminated_message_log", identifier)
        records = [json.loads(line) for line in raw.splitlines()]
        previous, contents, deliveries = None, {}, {}
        for index, event in enumerate(records):
            location = f"{identifier}/message-ledger.jsonl#{index}"
            unsealed = dict(event)
            stored = unsealed.pop("record_sha256")
            self.require(digest(encode(unsealed)) == stored, "message_chain_sha256", location)
            self.require(event["previous_sha256"] == previous, "message_chain_previous", location)
            previous = stored
            ident = event["id"]
            if event["event"] == "content":
                self.require(type(ident) is int and ident == len(contents) + 1, "message_sequence", location)
                self.require(ident not in contents, "unique_content_id", location)
                content = event["content"].encode("utf-8")
                self.require(digest(content) == event["sha256"], "message_content_sha256", location)
                self.require(type(event["utf8_bytes"]) is int and len(content) == event["utf8_bytes"], "message_utf8_size", location)
                self.require(event["mode"] == closure["mode"], "message_mode", location)
                contents[ident] = event
            elif event["event"] == "delivery":
                self.require(ident in contents and ident not in deliveries, "delivery_sequence", location)
                self.require(event["status"] in ("supplied_to_client", "not_supplied", "unknown", "reference_rendered"), "delivery_status_enum", location)
                deliveries[ident] = event["status"]
            else:
                self.require(False, "known_message_record_kind", location)
        self.require(closure["log_sha256"] == digest(raw), "public_log_closure_sha256", identifier)
        self.require(closure["record_count"] == len(records), "public_record_count", identifier)
        self.require(closure["message_count"] == len(contents), "public_message_count", identifier)
        self.require(closure["delivery_count"] == len(deliveries), "public_delivery_count", identifier)
        self.require(closure["last_record_sha256"] == previous, "public_terminal_record", identifier)
        categories, components, tools = Counter(), Counter(), Counter()
        timing_bytes, unknown, not_supplied = 0, 0, 0
        names, substantive = [], 0
        for ident, item in contents.items():
            status = deliveries.get(ident, "unknown")
            if status == "not_supplied":
                not_supplied += 1
                continue
            if status != "supplied_to_client":
                unknown += 1
                continue
            text = item["content"]
            size = len(text.encode("utf-8"))
            category = item["category"]
            categories[category] += size
            if not category.startswith("driver_"):
                continue
            rendered = json.loads(text)
            self.require(text.encode("utf-8") == encode(rendered), "public_driver_serialization", identifier)
            result = rendered["tool_result"]["result"]
            tool = rendered["tool_result"]["tool"]
            tools[tool] += 1
            self.require(category == "driver_" + tool + "_and_continuation", "driver_category", identifier)
            if tool == "read_context":
                docs = result["documents"]
                names.extend(doc["name"] for doc in docs)
                raw_docs = sum(len(doc["content"].encode("utf-8")) for doc in docs)
                encoded_docs = sum(len(encode(doc)) for doc in docs)
                escaped = sum(len(encode(doc["content"])) - 2 for doc in docs)
                substantive += raw_docs
                components["retrieval_escaped_content"] += escaped
                components["retrieval_document_structure"] += encoded_docs - escaped
                components["retrieval_result_structure"] += len(encode(result)) - encoded_docs
                components["retrieval_driver_wrapper_and_continuation"] += size - len(encode(result))
            elif tool == "release":
                normalized = json.loads(text)
                value = normalized["tool_result"]["result"]["runtime_seconds"]
                self.require(type(value) in (int, float) and value >= 0, "gate_runtime_numeric", identifier)
                normalized["tool_result"]["result"]["runtime_seconds"] = 0
                timing_bytes += size - len(encode(normalized))
        self.require(unknown == 0, "fully_known_public_delivery_accounting", identifier)
        retrieval_category = categories["driver_read_context_and_continuation"]
        self.require(sum(components.values()) == retrieval_category, "retrieval_component_sum", identifier)
        total = sum(categories.values())
        row = {"cell": cell, "study_supplied_message_bytes": total if not unknown else None,
               "categories": dict(categories), "components": dict(components), "recorded_supplied_messages": sum(v == "supplied_to_client" for v in deliveries.values()),
               "unknown_delivery_messages": unknown, "not_supplied_messages": not_supplied,
               "retrieval_document_content_utf8": substantive, "retrieved_names": names,
               "driver_tool_counts": dict(tools), "gate_runtime_serialization_bytes_above_zero": timing_bytes,
               "message_bytes_with_gate_runtime_zeroed": total - timing_bytes if not unknown else None}
        for name, value in categories.items():
            row["category:" + name] = value
        for name, value in components.items():
            row["component:" + name] = value
        return row

    def contrast(self, rows, metric, cfg):
        groups = []
        for case, state in itertools.product(cfg["case_ids"], cfg["states"]):
            cells, means = {}, {}
            for arm, regime in itertools.product(cfg["arms"], cfg["regimes"]):
                selected = [r for r in rows if (r["cell"]["case"], r["cell"]["state"], r["cell"]["arm"], r["cell"]["regime"]) == (case, state, arm, regime)]
                values = [r[metric] for r in selected]
                known = all(type(v) is int for v in values)
                self.require(len(values) == len(cfg["repetitions"]) and known, "complete_byte_contrast_cell", [metric, case, state, arm, regime])
                if not known or not values:
                    raise ValueError("Cannot compute complete byte contrast from missing/noninteger values")
                key = arm + "_" + regime
                mean = Fraction(sum(values), len(values))
                means[key] = mean
                cells[key] = {"n": len(values), "sum": sum(values), "mean": fraction(mean)}
            dg = means["G_distributed"] - means["G_bundled"]
            dp = means["P_distributed"] - means["P_bundled"]
            groups.append({"case": case, "state": state, "cells": cells,
                           "delta_G": fraction(dg), "delta_P": fraction(dp), "interaction": fraction(dp - dg)})
        aggregate = {key: fraction(sum(Fraction(g[key]["exact"]) for g in groups) / len(groups)) for key in ("delta_G", "delta_P", "interaction")}
        return {"metric": metric, "case_state": groups, "equal_case_state_aggregate": aggregate,
                "weighting": "Equal case/state weights; complete repeated cells; no weighting by session completion."}

    def run(self):
        lineage = self.obj("access-redaction-map.json")
        cfg = self.obj(CONFIG)
        assignment = self.obj(COHORT / "assignment.json")
        cells = assignment["assigned"]
        ids = [c["opaque_id"] for c in cells]
        actual = [(c["case"], c["state"], c["arm"], c["regime"], c["repetition"]) for c in cells]
        expected = set(itertools.product(cfg["case_ids"], cfg["states"], cfg["arms"], cfg["regimes"], cfg["repetitions"]))
        self.require(len(ids) == len(set(ids)) == len(actual) == len(expected) and set(actual) == expected, "complete_public_assignment_frame")
        rows = [self.session(cell) for cell in cells]
        category_names = sorted({key for row in rows for key in row["categories"]})
        component_names = sorted({key for row in rows for key in row["components"]})
        for row in rows:
            for key in category_names:
                row.setdefault("category:" + key, 0)
            for key in component_names:
                row.setdefault("component:" + key, 0)
        metrics = ["study_supplied_message_bytes", "gate_runtime_serialization_bytes_above_zero", "message_bytes_with_gate_runtime_zeroed", "retrieval_document_content_utf8"]
        metrics += ["category:" + key for key in category_names] + ["component:" + key for key in component_names]
        contrasts = {metric: self.contrast(rows, metric, cfg) for metric in metrics}
        conditions = []
        for arm, regime in itertools.product(cfg["arms"], cfg["regimes"]):
            selected = [r for r in rows if (r["cell"]["arm"], r["cell"]["regime"]) == (arm, regime)]
            total = sum(r["study_supplied_message_bytes"] for r in selected)
            categories = sum((Counter(r["categories"]) for r in selected), Counter())
            conditions.append({"arm": arm, "regime": regime, "n": len(selected), "message_bytes_sum": total,
                               "message_bytes_mean": fraction(Fraction(total, len(selected))), "category_sums": dict(categories)})
        # Deliberately first access to the preserved evaluation: reconstruction is complete.
        preserved = self.obj(COHORT / "evaluation-original.json")
        original_rows = {r["cell"]["opaque_id"]: r for r in preserved["rows"]}
        self.require(set(original_rows) == set(ids), "preserved_evaluation_frame")
        for row in rows:
            original = original_rows[row["cell"]["opaque_id"]]
            self.require(row["cell"] == original["cell"], "preserved_cell", row["cell"]["opaque_id"])
            self.require(row["study_supplied_message_bytes"] == original["study_supplied_message_bytes"], "preserved_message_bytes", row["cell"]["opaque_id"])
            recorded = {key: value["known_bytes"] for key, value in original["study_message_ledger"]["categories"].items()}
            self.require(row["categories"] == recorded, "preserved_category_bytes", row["cell"]["opaque_id"])
        original_contrast = next(c for c in preserved["contrasts"] if c["metric"] == "study_supplied_message_bytes")
        reconstructed = contrasts["study_supplied_message_bytes"]
        for key in ("delta_G", "delta_P", "interaction"):
            self.require(abs(original_contrast["equal_case_state_aggregate"][key] - reconstructed["equal_case_state_aggregate"][key]["decimal"]) < 1e-9, "preserved_aggregate_contrast", key)
        for group in reconstructed["case_state"]:
            prior = next(c for c in original_contrast["case_state"] if (c["case"], c["state"]) == (group["case"], group["state"]))
            for key in ("delta_G", "delta_P", "interaction"):
                self.require(abs(prior[key] - group[key]["decimal"]) < 1e-9, "preserved_case_state_contrast", [group["case"], group["state"], key])
        # Check consumed bytes did not change while being audited. Do not claim the
        # remainder of the public package, historical freeze or hidden originals.
        for name, info in self.inputs.items():
            self.require(digest((self.root / name).read_bytes()) == info["sha256"], "consumed_input_stable", name)
        components = {key: contrasts[key]["equal_case_state_aggregate"] for key in (
            "component:retrieval_driver_wrapper_and_continuation", "component:retrieval_result_structure",
            "category:driver_list_context_and_continuation", "gate_runtime_serialization_bytes_above_zero")}
        return {"schema": "public-byte-audit-v1", "created_at": datetime.now(timezone.utc).isoformat(),
                "passed": not self.errors, "checks": self.checks, "errors": self.errors, "package": str(self.root),
                "script_sha256": digest(Path(__file__).read_bytes()), "export_manifest_sha256": self.manifest_sha256,
                "scope": "Public derivative message bytes and accounting only; no outcome, gate or model audit.",
                "network_calls": 0, "model_calls": 0, "study_imports": False,
                "frame": {"assignments": len(cells), "cases": cfg["case_ids"], "states": cfg["states"],
                          "arms": cfg["arms"], "regimes": cfg["regimes"], "repetitions": cfg["repetitions"]},
                "total_message_bytes": sum(r["study_supplied_message_bytes"] for r in rows),
                "total_category_bytes": dict(sum((Counter(r["categories"]) for r in rows), Counter())),
                "conditions": conditions, "contrasts": contrasts, "mechanical_decomposition": components, "sessions": rows,
                "public_integrity": {"verified": "Consumed files against public export hashes; content and record chains; full-log/count/terminal message closures; derived session/end/start bindings; input stability.",
                                     "consumed_file_count": len(self.inputs), "inputs": self.inputs,
                                     "not_verified": "No detached signature, DOI-server identity, whole-package inventory, original frozen integrity, hidden text, real argv, provider identity or client/model receipt."},
                "derivative_qualification": {"public_declaration": lineage.get("qualification"),
                                             "declared_original_lengths_preserved": lineage.get("original_utf8_lengths_preserved"),
                                             "declared_originals_modified": lineage.get("originals_modified"),
                                             "declared_seal_lineage_present": lineage.get("original_seals_preserved_in_lineage_not_claimed_as_derivative_seals"),
                                             "audit_interpretation": "These declarations are not independent proof of hidden originals. This audit verifies derivative consistency and equality with the preserved numeric evaluation only."},
                "interpretation_limits": ["The actual-byte primary contrast is unchanged; zeroing only runtime_seconds is diagnostic decomposition, not endpoint replacement.",
                                          "Recorded supplied_to_client labels are audited public data, not independently observed delivery.",
                                          "Equal-length pseudonyms permit byte reconstruction but do not authenticate omitted text, private streams or argv.",
                                          "No p-values, confidence intervals, efficiency, reasoning, billing or provider claims."]}


def find_package(path):
    path = path.resolve()
    for candidate in (path, *path.parents):
        if (candidate / "export-manifest.json").is_file() and (candidate / COHORT / "assignment.json").is_file():
            return candidate
    raise ValueError("--cohort must locate an extracted public package with export-manifest.json and cohort-001")


def negative_test(root, successful):
    if not successful["passed"]:
        return {"passed": False, "reason": "Positive audit failed; negative test not run."}
    with tempfile.TemporaryDirectory(prefix="public-byte-audit-negative-") as tmp:
        copied = Path(tmp) / "package"
        for relative in successful["public_integrity"]["inputs"]:
            target = copied / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / relative, target)
        cell = successful["sessions"][0]["cell"]
        relative = COHORT / "sessions" / cell["opaque_id"] / "message-ledger.jsonl"
        target = copied / relative
        before = target.read_bytes()
        records = before.splitlines(keepends=True)
        first = json.loads(records[0])
        text = first["content"]
        replacement = "X" if text[0] != "X" else "Y"
        first["content"] = replacement + text[1:]
        altered = encode(first) + b"\n" + b"".join(records[1:])
        if len(altered) != len(before) or altered == before:
            raise ValueError("Negative control must change content without changing total bytes")
        target.write_bytes(altered)
        failed = Auditor(copied).run()
        codes = Counter(e["code"] for e in failed["errors"])
        expected = {"public_file_sha256", "message_content_sha256", "message_chain_sha256", "public_log_closure_sha256"}
        passed = not failed["passed"] and expected.issubset(codes)
        return {"passed": passed, "mutation": "One same-length character in the first public message content; all public seals and closures left unchanged.",
                "mutated_relative_path": relative.as_posix(), "before_sha256": digest(before), "after_sha256": digest(altered),
                "bytes_before": len(before), "bytes_after": len(altered), "tampered_audit_passed": failed["passed"],
                "rejection_codes": dict(codes), "errors": failed["errors"],
                "original_public_package_modified": False, "temporary_copy": "Consumed public files only; deleted on exit."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true", help="Reject a same-length modified message in a disposable copy")
    args = parser.parse_args()
    root = find_package(args.cohort)
    output = args.output.resolve()
    if output.exists():
        parser.error("--output must be a new file; existing files are never overwritten")
    if output.is_relative_to(root):
        parser.error("--output must be outside the input package")
    audit = Auditor(root)
    try:
        result = audit.run()
        if args.self_test:
            result["negative_control"] = negative_test(root, result)
            result["passed"] = result["passed"] and result["negative_control"]["passed"]
    except (OSError, ValueError, TypeError, KeyError, IndexError, StopIteration) as exc:
        result = {"schema": "public-byte-audit-v1", "passed": False, "package": str(root),
                  "errors": audit.errors + [{"code": "audit_exception", "detail": type(exc).__name__ + ": " + str(exc)}]}
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    brief = {"passed": result["passed"], "receipt": str(output), "checks": result.get("checks"),
             "total_message_bytes": result.get("total_message_bytes"), "errors": result.get("errors")}
    if "contrasts" in result:
        brief["primary_byte_contrast"] = result["contrasts"]["study_supplied_message_bytes"]["equal_case_state_aggregate"]
        brief["decomposition"] = result["mechanical_decomposition"]
    if "negative_control" in result:
        brief["negative_control_passed"] = result["negative_control"]["passed"]
        brief["negative_rejection_codes"] = result["negative_control"].get("rejection_codes")
    print(json.dumps(brief, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
