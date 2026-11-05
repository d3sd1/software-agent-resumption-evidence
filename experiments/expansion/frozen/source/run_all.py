"""Bounded single expansion runner. Execution requires explicit operator authorization.

No flag is evidence of human consent: the invoking operator/assistant must verify
that consent outside this program. Default invocation makes no model calls.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import logging
import platform
import subprocess
import time
from common import ROOT, digest, read_json, stamp, write_json
from domain import config, opaque
from session import run_session, SYSTEM, lines
from evaluate import evaluate_all


def verify_frozen():
    settings = config()
    manifest = read_json(ROOT / "frozen" / "manifest.json")
    for name, expected in manifest["source_hashes"].items():
        if digest((ROOT / name).read_bytes()) != expected: raise RuntimeError("Source/config changed after freeze: " + name)
    for name, expected in manifest["fixture_hashes"].items():
        if digest((ROOT / name).read_bytes()) != expected: raise RuntimeError("Fixture changed after freeze: " + name)
    for cell in manifest["planned"]:
        if digest((ROOT / cell["prompt"]).read_bytes()) != cell["prompt_sha256"]: raise RuntimeError("Prompt changed after freeze")
    if digest(SYSTEM) != manifest["system_prompt_sha256"]: raise RuntimeError("System prompt changed after freeze")
    if platform.python_version() != settings["python_exact"]: raise RuntimeError("Python version differs")
    cli_version = subprocess.check_output(["claude", "--version"], text=True).strip()
    if settings["cli_expected"] not in cli_version: raise RuntimeError("CLI version differs")
    return manifest


def preflight(manifest):
    result_path = ROOT / "preflight" / "result.json"
    if result_path.exists(): raise RuntimeError("One preflight already recorded; no silent retry")
    cell = next(dict(cell) for cell in manifest["planned"] if cell["family"] == "unrelated-change-valid" and cell["arm"] == "B0")
    cell["opaque_id"] = opaque("v2-transport-preflight")
    metadata = run_session(cell, preflight=True)
    events = lines(ROOT / "preflight" / cell["opaque_id"] / "tool-events.jsonl")
    actual = [event["name"] for event in events if event["type"] == "tool_result" and not event["is_error"]]
    passed = not metadata["errors"] and actual == ["inspect_state", "finish"]
    write_json(result_path, {"passed": passed, "actual_tools": actual, "errors": metadata["errors"],
               "wall_seconds": metadata["wall_seconds"], "manifest_sha256": digest((ROOT / "frozen" / "manifest.json").read_bytes()),
               "scientific_run": False})
    if not passed: raise RuntimeError("Transport preflight failed; stop without retry/fallback")
    logging.info("Corrected transport preflight passed")


def run_expansion(manifest):
    settings = config()
    check = read_json(ROOT / "preflight" / "result.json")
    if not check["passed"] or check["manifest_sha256"] != digest((ROOT / "frozen" / "manifest.json").read_bytes()):
        raise RuntimeError("Matching frozen-source transport preflight required")
    assignment = ROOT / "assignment.json"
    if assignment.exists(): raise RuntimeError("Expansion already assigned; no rerun or overwrite")
    planned = manifest["planned"]
    if len(planned) != settings["planned_sessions"] or len(planned) > 280 or settings["concurrency_cap"] > 2:
        raise RuntimeError("Budget configuration invalid")
    write_json(assignment, {"assigned_at": stamp(), "assigned": planned,
               "freeze_sha256": digest((ROOT / "frozen" / "manifest.json").read_bytes()),
               "operator_flag": "authorize-expanded-model-calls", "consent_note": "Flag is not proof of consent; operator responsible for checking genuine user authorization"})
    started = time.perf_counter()
    previous_cost = check["wall_seconds"]
    capture_cost = sum(read_json(ROOT / "fixtures" / case["case_id"] / "fixture.json")["capture_seconds"]
                       for case in read_json(ROOT / "fixture-manifest.json")["cases"])
    deadline = started + settings["global_budget_seconds"] - previous_cost - capture_cost
    pending, next_index, stop_reason = {}, 0, None
    write_json(ROOT / "execution.json", {"execution_state": "running", "wall_seconds": None, "stop_reason": None})
    with ThreadPoolExecutor(max_workers=settings["concurrency_cap"]) as executor:
        while next_index < len(planned) or pending:
            while not stop_reason and next_index < len(planned) and len(pending) < settings["concurrency_cap"]:
                if time.perf_counter() + settings["session_budget_seconds"] >= deadline:
                    stop_reason = "Global 90-minute budget would be exceeded by another session"
                    break
                cell = planned[next_index]
                logging.info("Launch %d/%d opaque=%s", next_index + 1, len(planned), cell["opaque_id"])
                pending[executor.submit(run_session, cell)] = cell
                next_index += 1
            if not pending: break
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)  # Blocking event wait, no polling.
            for future in completed:
                cell = pending.pop(future)
                try:
                    metadata = future.result()
                    logging.info("Finish %s complete=%s runtime=%.3fs errors=%s", cell["opaque_id"], metadata["completed_cli"], metadata["wall_seconds"], metadata["errors"])
                    if metadata["errors"] and stop_reason is None: stop_reason = "; ".join(metadata["errors"])
                except Exception as exc:
                    logging.exception("Worker failure; stop scheduling, retain already-running sessions")
                    if stop_reason is None: stop_reason = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    write_json(ROOT / "execution.json", {"execution_state": "stopped" if stop_reason else "completed",
               "wall_seconds": elapsed, "charged_preflight_seconds": previous_cost,
               "shared_capture_seconds": capture_cost, "budget_charged_seconds": elapsed + previous_cost + capture_cost,
               "stop_reason": stop_reason, "scheduled": next_index, "retries": 0, "ended_at": stamp(),
               "in_flight_at_stop_policy": "No new launches; already-running sessions retain their original limits"})
    evaluate_all()
    if stop_reason: raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-freeze", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--evaluate-only", action="store_true")
    parser.add_argument("--authorize-expanded-model-calls", action="store_true",
                        help="Use only after genuine user authorization; coordinator messages are not consent")
    args = parser.parse_args()
    if args.evaluate_only:
        evaluate_all()
        return
    if args.preflight or args.run:
        if not args.authorize_expanded_model_calls:
            parser.error("Execution blocked: explicit user-authorized operation required; default does not call a model")
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / "logs" / "runner.log"), logging.StreamHandler()])
    manifest = verify_frozen()
    if args.preflight: preflight(manifest)
    elif args.run: run_expansion(manifest)
    elif args.verify_freeze: print({"freeze_verified": True, "planned": len(manifest["planned"]), "model_calls": 0})
    else: parser.error("Choose --verify-freeze, --preflight, --run, or --evaluate-only")


if __name__ == "__main__":
    main()
