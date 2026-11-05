"""SINGLE USE runner adapted from expansion/run_all.py. Never invokes preflight.

The --run flag is necessary, not evidence of consent. Coordinator must validate,
freeze and separately verify genuine authorization before invoking this path.
"""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
import subprocess
import time
from .common import ROOT, read, write, sha, stamp, settings, append
from .freeze import verify
from .session import run_session
from .evaluate import evaluate_run


def claim_once(root, payload):
    # Exclusive creation is atomic across competing runner processes.
    write(Path(root) / "RUN-CLAIM.json", payload)


# Exact emitted records, not substring matching or a termination-label exemption.
# Any additional/unrecognized error remains fatal even with an expected-limit label.
EXPECTED_SLOT_LIMIT_ERRORS = {
    "action_cap": ["RuntimeError: Action cap without finish"],
    "deadline": ["session_timeout"],
    "session_deadline": ["RuntimeError: session_deadline"],
    "deadline_during_preparation": ["deadline_during_preparation: TimeoutError: deadline_during_preparation"],
}


def classify_transport(transport):
    """Decide scheduling from all reported operational errors, never from success.

    Expected action/time limits are slot-level non-completions. Quota/auth/tool/
    identity/instrument failures and inconsistent/unknown records stop scheduling.
    This does not modify the slot's original termination, errors or outcome.
    """
    if not isinstance(transport, dict):
        return {"scope": "cohort", "classification": "invalid_transport_record", "stop": True}
    termination, errors = transport.get("termination"), transport.get("errors")
    if not isinstance(errors, list) or not all(isinstance(error, str) for error in errors):
        return {"scope": "cohort", "classification": "invalid_error_record", "stop": True}
    if termination == "structured_finish" and not errors:
        return {"scope": "slot", "classification": "structured_finish", "stop": False}
    expected = EXPECTED_SLOT_LIMIT_ERRORS.get(termination)
    if expected is not None and errors == expected:
        return {"scope": "slot", "classification": "expected_" + termination, "stop": False}
    return {"scope": "cohort", "classification": "fatal_transport_or_instrument",
            "stop": True, "termination": termination, "errors": errors}


def schedule_slots(planned, cfg, deadline, launch, emit):
    """Shared production/test scheduler. Tests inject local deterministic workers.

    Worker callbacks are never retried. In-flight workers keep their own bounds;
    a fatal route/instrument record prevents subsequent launches, not their capture.
    """
    pending, index, stop = {}, 0, None
    with ThreadPoolExecutor(max_workers=cfg["workers"]) as executor:
        while index < len(planned) or pending:
            while not stop and index < len(planned) and len(pending) < cfg["workers"]:
                if time.monotonic() + cfg["session_seconds"] >= deadline:
                    stop = "global_budget_prevents_full_next_session"
                    break
                cell = planned[index]
                emit({"event": "launch_attempt", "cell": cell, "at": stamp()})
                pending[executor.submit(launch, cell)] = cell
                index += 1
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                cell = pending.pop(future)
                try:
                    result = future.result()
                    decision = classify_transport(result.get("transport"))
                    transport = result.get("transport") or {}
                    emit({"event": "session_returned", "id": cell["opaque_id"],
                          "launched": transport.get("launched"), "errors": transport.get("errors"),
                          "termination": transport.get("termination"), "scheduling_decision": decision,
                          "at": stamp()})
                    if decision["stop"] and stop is None:
                        stop = "transport_or_instrument_stop: " + decision["classification"]
                except Exception as exc:
                    emit({"event": "worker_exception", "id": cell["opaque_id"], "error": repr(exc), "at": stamp()})
                    stop = stop or "worker_exception"
    return {"attempted": index, "unlaunched": len(planned) - index, "stop_reason": stop}


def run(frozen, output, authorization):
    frozen, output = Path(frozen), Path(output)
    manifest = verify(frozen)
    auth = read(authorization)
    digest = sha((frozen / "manifest.json").read_bytes())
    if (auth.get("freeze_sha256") != digest or auth.get("participant_run_authorized") is not True
            or not auth.get("authorization_reference")):
        raise RuntimeError("Matching authorization audit record required; record is not itself consent")
    cli = subprocess.check_output(["claude", "--version"], text=True).strip()
    if cli != manifest["cli_version"]:
        raise RuntimeError("CLI route version changed; coordinator revalidation needed")
    if output.exists():
        raise RuntimeError("Output already exists; no rerun")
    cfg = settings()
    start = time.monotonic()
    deadline = start + cfg["global_seconds"] - manifest["shared_preflight_seconds"]
    claim_once(ROOT, {"at": stamp(), "freeze_sha256": digest, "output": str(output.relative_to(ROOT)),
                      "authorization_reference": auth["authorization_reference"], "single_use": True})
    output.mkdir(parents=True, exist_ok=False)
    planned = manifest["planned"]
    write(output / "assignment.json", {"at": stamp(), "assigned": planned, "freeze_sha256": digest,
                                       "status": "all assigned before any participant exposure"})
    append(output / "flow.jsonl", {"event": "assigned", "count": len(planned), "at": stamp()})
    scheduling = schedule_slots(
        planned, cfg, deadline,
        lambda cell: run_session(frozen, manifest, cell, output / "sessions" / cell["opaque_id"]),
        lambda event: append(output / "flow.jsonl", event))
    for cell in planned[scheduling["attempted"]:]:
        append(output / "flow.jsonl", {"event": "unlaunched", "id": cell["opaque_id"],
                                      "reason": scheduling["stop_reason"], "at": stamp()})
    write(output / "execution.json", {**scheduling, "wall_seconds": time.monotonic() - start,
                                      "shared_preflight_seconds": manifest["shared_preflight_seconds"],
                                      "retries": 0,
                                      "slot_limit_policy": "Expected action-cap/deadline closes only its slot; subsequent assignments continue",
                                      "in_flight_policy": "On fatal route/instrument stop, retain original deadlines; no new launches"})
    return evaluate_run(output)
