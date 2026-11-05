"""Started-slot endpoints and exact newly supplied bytes, protocol-v1 sections 7/8."""
from pathlib import Path
import statistics
from .common import read, write, sha, settings
from .oracle import evaluate as event_evaluate
from .messages import measure

METRICS = ("success", "study_supplied_message_bytes", "automatic_bytes", "context_payload_bytes",
           "unsupported_request", "unsupported_commit", "wall_seconds", "input_tokens", "output_tokens",
           "cache_read_input_tokens", "cache_creation_input_tokens", "retrieval_calls", "unique_document_bytes",
           "repeated_documents", "retrieval_errors", "release_requests", "checks", "gate_seconds",
           "check_seconds", "automatic_seconds", "logical_acquisition_bytes_sum")


def average(values):
    known = [float(x) for x in values if x is not None]
    return {"mean": statistics.mean(known) if known else None,
            "std": statistics.stdev(known) if len(known) > 1 else None,
            "observed": len(known), "missing": len(values) - len(known),
            "interval": None, "interval_note": "Finite-suite description; no degenerate bootstrap for zero endpoints"}


def contrasts(rows, metric, cfg=None):
    cfg = cfg or settings()
    results = []
    for case in cfg["case_ids"]:
        for state in cfg["states"]:
            cells = {}
            for arm in cfg["arms"]:
                for regime in cfg["regimes"]:
                    selected = [r for r in rows if r["cell"]["case"] == case and r["cell"]["state"] == state
                                and r["cell"]["arm"] == arm and r["cell"]["regime"] == regime]
                    values = [r.get(metric) for r in selected]
                    if len(values) < len(cfg["repetitions"]):
                        values += [None] * (len(cfg["repetitions"]) - len(values))
                    summary = average(values)
                    summary["unstarted"] = sum(r.get("status") == "never_started" for r in selected)
                    summary["excluded_missing_or_incomplete_ledger"] = sum(r.get(metric) is None for r in selected)
                    if metric == "success":
                        summary["successful_completions"] = sum(v is True for v in values)
                        summary["completion_known_slots"] = summary["observed"]
                        summary["known_started_slots"] = sum(r.get("status") in ("auditable_started", "started_lifecycle_unknown") for r in selected)
                        summary["completion_unknown_slots"] = sum(r.get("status") in ("auditable_started", "started_lifecycle_unknown") and r.get(metric) is None for r in selected)
                        summary["mean_is_observed_subset_if_missing"] = summary["missing"] > 0
                    cells[arm + "_" + regime] = summary
            full, subset = {}, {}
            for arm in cfg["arms"]:
                b, d = cells[arm + "_bundled"], cells[arm + "_distributed"]
                subset[arm] = None if b["mean"] is None or d["mean"] is None else d["mean"] - b["mean"]
                full[arm] = subset[arm] if b["missing"] == 0 and d["missing"] == 0 else None
            interaction = None if any(full[a] is None for a in cfg["arms"]) else full["P"] - full["G"]
            subset_i = None if any(subset[a] is None for a in cfg["arms"]) else subset["P"] - subset["G"]
            results.append({"case": case, "state": state, "cells": cells,
                            "delta_G": full["G"], "delta_P": full["P"], "interaction": interaction,
                            "observed_subset_delta_G": subset["G"], "observed_subset_delta_P": subset["P"],
                            "observed_subset_interaction": subset_i})
    aggregate, observed = {}, {}
    for field in ("delta_G", "delta_P", "interaction"):
        values = [r[field] for r in results]
        aggregate[field] = statistics.mean(values) if values and all(v is not None for v in values) else None
        partial = [r["observed_subset_" + field] for r in results if r["observed_subset_" + field] is not None]
        observed[field] = {"mean": statistics.mean(partial) if partial else None,
                           "case_state_coverage": len(partial), "case_state_planned": len(results)}
    blocks, excluded = [], []
    for case in cfg["case_ids"]:
        for state in cfg["states"]:
            for rep in cfg["repetitions"]:
                block = [r for r in rows if (r["cell"]["case"], r["cell"]["state"], r["cell"]["repetition"]) == (case, state, rep)]
                key = {"case": case, "state": state, "repetition": rep}
                values = {(r["cell"]["arm"], r["cell"]["regime"]): r.get(metric) for r in block}
                if len(values) != 4 or any(v is None for v in values.values()):
                    excluded.append(key)
                else:
                    dg = float(values[("G", "distributed")]) - float(values[("G", "bundled")])
                    dp = float(values[("P", "distributed")]) - float(values[("P", "bundled")])
                    blocks.append({**key, "delta_G": dg, "delta_P": dp, "interaction": dp - dg})
    return {"metric": metric, "case_state": results, "equal_case_state_aggregate": aggregate,
            "observed_subset_NOT_full_suite": observed,
            "weighting": "Equal case/state weights; missing/unstarted required assignment makes full-suite contrast unavailable. Observed subset explicitly separate.",
            "secondary_complete_blocks": blocks, "excluded_incomplete_blocks": excluded}


def audited_slot(folder, cell):
    start_path, end_path, session_path = folder / "slot-start.json", folder / "slot-end.json", folder / "session.json"
    if not start_path.exists():
        return None, "lifecycle_unknown" if folder.exists() else "never_started"
    try:
        start = read(start_path)
    except (ValueError, OSError):
        return None, "lifecycle_unknown"
    if not isinstance(start, dict) or start.get("cell") != cell:
        return None, "lifecycle_unknown"
    if not end_path.exists() or not session_path.exists():
        return None, "started_lifecycle_unknown"
    try:
        end, session = read(end_path), read(session_path)
    except (ValueError, OSError):
        return None, "started_lifecycle_unknown"
    if (not isinstance(end, dict) or not isinstance(session, dict) or session.get("cell") != cell
            or end.get("slot_start_sha256") != sha(start_path.read_bytes())
            or session.get("slot_start_sha256") != sha(start_path.read_bytes())
            or end.get("session_sha256") != sha(session_path.read_bytes())):
        return None, "started_lifecycle_unknown"
    return session, "auditable_started"


def evaluate_run(folder):
    folder = Path(folder)
    assigned = read(folder / "assignment.json")["assigned"]
    rows = []
    flow = {"assigned": len(assigned), "known_started": 0, "auditable_started": 0,
            "completion_known": 0, "completion_unknown": 0, "workload_known": 0, "workload_unknown": 0,
            "recipient_launched": 0, "launch_unknown": 0, "final_dispositions": 0, "never_started": 0,
            "lifecycle_unknown": 0, "started_lifecycle_unknown": 0,
            "operationally_incomplete": 0, "supported_completions": 0}
    for cell in assigned:
        workspace = folder / "sessions" / cell["opaque_id"]
        row = {"cell": cell, **dict.fromkeys(METRICS)}
        try:
            metadata, status = audited_slot(workspace, cell)
        except (ValueError, OSError, KeyError):
            metadata, status = None, "lifecycle_unknown"
        row["status"] = status
        if metadata is None:
            flow[status] += 1
            row.update(completion_audit="unknown", workload_audit="unknown")
            if status == "started_lifecycle_unknown":
                flow["known_started"] += 1
                flow["completion_unknown"] += 1
                flow["workload_unknown"] += 1
                flow["launch_unknown"] += 1
            if workspace.exists():
                try:
                    row["observed_prefix"] = event_evaluate(workspace, {"termination": "missing_lifecycle"})
                except (ValueError, OSError, KeyError, RuntimeError) as exc:
                    row["audit_error"] = str(exc)
            rows.append(row)
            continue
        # Lifecycle, event completeness and byte completeness are independent audit axes.
        # A damaged message counter MUST NOT remove a valid completion from its denominator.
        flow["known_started"] += 1
        flow["auditable_started"] += 1
        transport, instrument = metadata["transport"], metadata.get("instrument")
        event_closure = metadata.get("event_closure")
        if instrument is not None and (not isinstance(event_closure, dict) or any(
                event_closure.get(key) != instrument.get(key) for key in ("actions", "last_event_sha256"))):
            event_closure = None
        outcome = event_evaluate(workspace, event_closure or {"termination": transport["termination"]})
        message_closure = metadata.get("message_closure")
        if message_closure != transport.get("message_closure"):
            message_closure = None
        try:
            messages = measure(workspace, message_closure)
        except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
            messages = {"bytes": None, "fully_accounted": False, "closure_verified": False,
                        "known_prefix_bytes": None, "audit_errors": ["message_measurement_exception: " + str(exc)]}
        flow["workload_known" if messages["fully_accounted"] else "workload_unknown"] += 1
        row.update(workload_audit="known" if messages["fully_accounted"] else "unknown",
                   completion_audit="known" if outcome["events_complete"] else "unknown",
                   event_audit=outcome["event_audit"])
        if transport["launched"] is True:
            flow["recipient_launched"] += 1
        elif transport["launched"] is None:
            flow["launch_unknown"] += 1
        if outcome["events_complete"]:
            flow["completion_known"] += 1
            if outcome["completed"]:
                flow["final_dispositions"] += 1
            else:
                flow["operationally_incomplete"] += 1
            success = outcome["success"] is True
            flow["supported_completions"] += int(success)
        else:
            flow["completion_unknown"] += 1
            success = None
        row.update(success=success, study_supplied_message_bytes=messages["bytes"],
                   wall_seconds=metadata["wall_seconds"], observed_prefix=outcome,
                   study_message_ledger=messages, termination=transport["termination"],
                   primary_completion_cause="event_record_unknown" if success is None else
                   "success" if success else outcome["classification"] if outcome["completed"] else transport["termination"],
                   provider_usage=transport["usage"], recipient_launched=transport["launched"])
        for metric in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            row[metric] = transport["usage"][metric]["value"]
        # Safety absence is NOT imputed from an incomplete exposed prefix.
        if outcome["completed"]:
            row.update(unsupported_request=outcome["unsupported_request"], unsupported_commit=outcome["unsupported_commit"])
        if instrument is not None:
            ledger = instrument["ledger"]
            row.update(prefix_workload=ledger, context_payload_bytes=ledger["retrieval"]["payload_bytes"],
                       automatic_bytes=ledger["automatic"]["bytes"], retrieval_calls=ledger["retrieval"]["calls"],
                       unique_document_bytes=ledger["retrieval"]["unique_document_bytes"],
                       repeated_documents=ledger["retrieval"]["repeated_documents"],
                       retrieval_errors=ledger["retrieval"]["errors"],
                       release_requests=outcome["observed_prefix_release_requests"], checks=len(ledger["checks"]),
                       gate_seconds=sum(g["runtime_seconds"] for g in ledger["gates"]),
                       check_seconds=sum(c["runtime_seconds"] for c in ledger["checks"]),
                       automatic_seconds=ledger["automatic"]["runtime_seconds"],
                       logical_acquisition_bytes_sum=ledger["retrieval"]["document_bytes"] + ledger["automatic"]["bytes"])
        rows.append(row)
    result = {"flow": flow, "rows": rows,
              "primary_completion_started_slots": {
                  "numerator": flow["supported_completions"] if not (flow["completion_unknown"] or flow["lifecycle_unknown"]) else None,
                  "denominator": flow["known_started"],
                  "denominator_note": "Known-start count retained even if event log/closure is lost; start-unknown slots separately counted",
                  "completion_unknown": flow["completion_unknown"], "start_unknown": flow["lifecycle_unknown"],
                  "observed_successes": flow["supported_completions"],
                  "observed_noncompletions": flow["completion_known"] - flow["supported_completions"],
                  "observed_subset_NOT_full_cohort": {"numerator": flow["supported_completions"],
                                                       "denominator": flow["completion_known"]}},
              "realized_collection_yield": {"observed_successes": flow["supported_completions"], "denominator": len(assigned),
                                            "completion_unknown": flow["completion_unknown"], "start_unknown": flow["lifecycle_unknown"]},
              "recipient_launch_yield": {"observed_launches": flow["recipient_launched"], "denominator": flow["known_started"],
                                         "launch_unknown": flow["launch_unknown"]},
              "observed_final_disposition_yield": {"observed_final_dispositions": flow["final_dispositions"], "denominator": flow["known_started"],
                                                   "completion_unknown": flow["completion_unknown"]},
              "conditional_final_session_success": {"numerator": flow["supported_completions"], "denominator": flow["final_dispositions"]},
              "workload_note": "All fully accounted started slots, including failures/caps/timeouts; low work from early failure is not efficiency. Unknown delivery null. Logical bytes != tokens != physical IO. No billing inference.",
              "contrasts": [contrasts(rows, name) for name in METRICS]}
    write(folder / "evaluation.json", result)
    return result
