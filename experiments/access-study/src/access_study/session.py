"""Prospective session seam adapted from expansion/session.py; no default calls."""
import time
from .common import read, write, sha, settings, stamp
from .harness import Harness
from .cli_bridge import system_prompt, execute, usage_from_deltas
from .oracle import evaluate
from .checker import environment
from .messages import MessageLedger, measure


def command(cfg):
    return ["claude", "--safe-mode", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--tools", "", "--permission-mode", "dontAsk", "--disable-slash-commands",
            "--no-session-persistence", "--output-format", "stream-json", "--input-format", "stream-json",
            "--verbose", "--max-turns", str(cfg["cli_max_turns"]), "--system-prompt", system_prompt(), "--print"]


def run_session(frozen, manifest, cell, folder):
    started = time.monotonic()
    cfg = settings()
    folder.mkdir(parents=True, exist_ok=False)
    # This durable start precedes ALL arm-specific acquisition/preparation.
    write(folder / "slot-start.json", {"cell": cell, "at": stamp(), "budget_seconds": cfg["session_seconds"],
                                       "boundary": "before arm-specific preparation"})
    harness = None
    instrument = None
    phase = "preparation_failure"
    bridge_entered = False
    transport = {"launched": False, "timeout": False, "errors": [], "results": [],
                 "usage": usage_from_deltas([]), "termination": phase, "cost": None,
                 "message_closure": None}
    try:
        harness = Harness(frozen / "prepared", cell, folder, deadline=started + cfg["session_seconds"], precreated=True)
        if environment() != harness.state["binding"]["environment"]:
            raise RuntimeError("Current interpreter/environment differs from frozen evidence binding")
        key = "__".join((cell["case"], cell["state"], cell["arm"]))
        if sha(harness.prompt.encode()) != manifest["prompt_hashes"][key]:
            raise RuntimeError("Frozen prompt differs before participant launch")
        if time.monotonic() >= harness.deadline:
            phase = "deadline_during_preparation"
            raise TimeoutError(phase)
        write(folder / "launch.json", {"at": stamp(), "cell": cell, "model_requested": "inherited; no override",
                                      "model_expected_from_preflight": manifest["model_identity"],
                                      "deadline_includes_arm_preparation": True})
        phase = "transport_failure"
        transport["launched"] = None  # Unexpected bridge failure cannot assert non-exposure.
        bridge_entered = True
        transport = execute(command(cfg), harness, manifest["model_identity"])
        phase = transport["termination"]
    except Exception as exc:
        transport["errors"].append(phase + ": " + type(exc).__name__ + ": " + str(exc))
        transport["termination"] = phase
    if harness is not None:
        instrument = harness.close(phase)
    # Before the bridge is entered, no study content can have been supplied. Record
    # an explicit closed empty ledger rather than interpreting a missing file as zero.
    if not bridge_entered and not (folder / "message-ledger.jsonl").exists():
        transport["message_closure"] = MessageLedger(folder).close()
    event_closure = ({"actions": instrument["actions"], "last_event_sha256": instrument["last_event_sha256"],
                      "termination": phase} if instrument is not None else
                     {"actions": 0, "last_event_sha256": None, "termination": phase})
    outcome = evaluate(folder, event_closure)
    metadata = {"cell": cell, "transport": transport, "instrument": instrument, "outcome": outcome,
                "event_closure": event_closure, "message_closure": transport.get("message_closure"),
                "wall_seconds": time.monotonic() - started, "ended_at": stamp(),
                "study_messages": measure(folder, transport.get("message_closure")),
                "slot_start_sha256": sha((folder / "slot-start.json").read_bytes())}
    write(folder / "session.json", metadata)
    write(folder / "slot-end.json", {"at": stamp(), "termination": phase,
                                     "slot_start_sha256": metadata["slot_start_sha256"],
                                     "session_sha256": sha((folder / "session.json").read_bytes()),
                                     "completion_within_envelope": (outcome["success"] is True) if outcome["events_complete"] else None,
                                     "not_a_reasoning_error": phase != "structured_finish"})
    return metadata
