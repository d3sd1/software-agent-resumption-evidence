"""Deterministic feasibility controls, never model participants or optimal policies."""
from pathlib import Path
import time
from .common import read, write, sha, canonical, inventory, settings, source_hashes
from .harness import Harness
from .oracle import evaluate, supported


def reference(harness, policy):
    """Declared privileged knowledge: recovery route and R/U authored state."""
    from .messages import MessageLedger, measure, response_content
    from .cli_bridge import system_prompt
    messages = MessageLedger(harness.folder, mode="reference_render_only_not_participant")
    messages.reference("initial_system_and_tool_definitions", system_prompt())
    messages.reference("initial_user_handoff", harness.prompt)
    def act(name, args=None):
        result, error, fatal = harness.call(name, args or {})
        if error or fatal:
            raise RuntimeError(str(result))
        if name != "finish":
            messages.reference("driver_" + name + "_and_continuation", response_content(name, result, error))
        return result
    if policy == "reference":
        directory = act("list_context")
        if harness.cell["regime"] == "bundled":
            act("read_context")
        else:
            for doc in directory["documents"]:
                act("read_context", {"name": doc["name"]})
        if harness.cell["state"] == "R":
            act("restore_verified")
        act("run_check", {"check": "functional"})
    elif policy == "always_restore":
        act("restore_verified")
    elif policy != "always_hold":
        raise ValueError("Unknown reference policy")
    if policy != "always_hold":
        result = act("release")
        if not result["allowed"]:
            raise RuntimeError("Prespecified recovery path did not deliver")
    act("finish", {"technical": "supported" if supported(harness.context()) else "unsupported",
                   "disposition": "delivered" if harness.commits else "hold",
                   "release_id": harness.commits[-1] if harness.commits else None,
                   "reason": "Deterministic instrument feasibility control; not participant behaviour"})
    message_closure = messages.close()
    harness.ledger["message_closure"] = message_closure
    harness.ledger["reference_rendered_messages_NOT_actual_supply"] = measure(harness.folder, message_closure)
    return harness.close("reference_policy_finished")


def verify_preparation(prepared, require_source=True):
    prepared = Path(prepared)
    receipt = read(prepared / "preparation.json")
    from .checker import environment
    if environment() != receipt["environment"]:
        raise RuntimeError("Current runtime differs from prepared binding")
    expected = receipt["artifact_hashes"]
    actual = inventory(prepared)
    actual.pop("preparation.json", None)
    if actual != expected:
        raise RuntimeError("Preparation artifact changed")
    if require_source and receipt["source_hashes"] != source_hashes():
        raise RuntimeError("Implementation changed since preparation; create a NEW preparation")
    return receipt


def validate(prepared, output):
    prepared, output = Path(prepared), Path(output)
    receipt = verify_preparation(prepared)
    output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    cfg = settings()
    rows, prompts, docs = [], {}, {}
    for case in cfg["case_ids"]:
        for state in cfg["states"]:
            for arm in cfg["arms"]:
                for regime in cfg["regimes"]:
                    cell = {"case": case, "state": state, "arm": arm, "regime": regime, "repetition": "control"}
                    for policy in ("reference", "always_restore", "always_hold"):
                        name = "__".join((case, state, arm, regime, policy))
                        harness = Harness(prepared, cell, output / name)
                        if policy == "reference":
                            key = (case, state, arm)
                            prompt_hash = sha(harness.prompt.encode())
                            if key in prompts and prompts[key] != prompt_hash:
                                raise RuntimeError("Initial bytes differ across access regimes")
                            prompts[key] = prompt_hash
                            doc_hashes = inventory(harness.start_dir / "documents")
                            if key in docs and docs[key] != doc_hashes:
                                raise RuntimeError("Document bytes differ across access regimes")
                            docs[key] = doc_hashes
                        metadata = reference(harness, policy)
                        outcome = evaluate(harness.folder, metadata)
                        if policy == "always_hold":
                            if outcome["success"] is not False or not outcome["missed_recoverable_opportunity"]:
                                raise RuntimeError("Hold was not classified as a missed positive")
                        elif outcome["success"] is not True:
                            raise RuntimeError("Recoverable reference failed")
                        if outcome["unsupported_request"] or outcome["unsupported_commit"]:
                            raise RuntimeError("Reference made unsupported request/commit")
                        rows.append({"cell": cell, "policy": policy, "actions": harness.actions,
                                     "outcome": outcome, "ledger": harness.ledger,
                                     "wall_seconds": metadata["wall_seconds"], "path": name})
    longest = max(row["actions"] for row in rows if row["policy"] == "reference")
    max_seconds = max(row["wall_seconds"] for row in rows)
    capacity = cfg["planned_sessions"] / cfg["workers"] * cfg["session_seconds"]
    viable = (longest <= 12 and cfg["action_cap"] >= 2 * longest + 8
              and max_seconds < cfg["session_seconds"]
              and capacity + receipt["shared_seconds"] < cfg["global_seconds"])
    summary = {"status": "locally_validated_not_frozen", "passed": viable, "model_calls": 0,
               "public_cases": len(cfg["case_ids"]), "controls": rows,
               "max_reference_actions": longest, "max_local_control_seconds": max_seconds,
               "capacity_seconds_excluding_overhead": capacity,
               "remaining_capacity_for_overhead_seconds": cfg["global_seconds"] - capacity - receipt["shared_seconds"],
               "feasibility_caveat": "Local control timing and slot arithmetic are not model-response runtime predictions; coordinator neutral preflight remains required",
               "elapsed_seconds": time.monotonic() - start,
               "source_hashes": source_hashes(), "preparation_sha256": sha((prepared / "preparation.json").read_bytes()),
               "parity": "Initial prompt and all complete document hashes equal within each arm across regimes",
               "artifact_hashes": inventory(output)}
    write(output / "validation.json", summary)
    return summary
