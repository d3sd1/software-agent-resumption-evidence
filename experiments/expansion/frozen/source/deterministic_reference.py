"""Always-recheck/repair reference, explicitly NON-MODEL and separate from seven arms."""
import time
from common import ROOT, read_json, write_json
from controls import reconciliation, gate
from domain import config, opaque
from harness import FixtureTools, prepare_run
from evaluate import score, aggregate


def main():
    settings = config()
    destination = ROOT / "reference"
    if destination.exists(): raise RuntimeError("Reference already executed; refuse overwrite")
    destination.mkdir()
    rows = []
    total_start = time.perf_counter()
    for case in read_json(ROOT / "fixture-manifest.json")["cases"]:
        started = time.perf_counter()
        fixture = read_json(ROOT / "fixtures" / case["case_id"] / "fixture.json")
        identifier = opaque(case["case_id"] + "|deterministic-reference")
        folder = destination / identifier
        # Apply exactly the conventional G/P gate, but do not call this an agent/model G run.
        prepare_run(folder, fixture, "G")
        tools = FixtureTools(folder, deadline=started + settings["session_budget_seconds"])
        inspected, error = tools.call("inspect_state", {})
        if error: raise RuntimeError(inspected)
        if inspected["policy"]["check"]:
            result, error = tools.call("run_check", {"name": "functional"})
            if error: raise RuntimeError(result)
            if result["evidence"]["outcome"] == "fail":
                tools.call("repair_component", {"multiplier": inspected["contract"]["target_percent"], "offset": 0})
                tools.call("run_check", {"name": "functional"})
        context = tools.context()
        technical = reconciliation(context)["technical_state"]
        decision = gate(context)
        if decision["allowed"]:
            result, error = tools.call("request_release", {})
            if error or not result["committed"]: raise RuntimeError(result)
            final = {"status": "released", "assessment": technical, "reason": "completed"}
        else:
            reason = ("authorization_revoked" if not context["policy"]["release"] else
                      "physical_unobservable" if "physical-fit" in context["contract"]["required_scopes"] else
                      "check_permission_revoked" if not context["policy"]["check"] else "technical_failure")
            final = {"status": "hold", "assessment": technical, "reason": reason}
        result, error = tools.call("finish", final)
        if error: raise RuntimeError(result)
        elapsed = time.perf_counter() - started
        write_json(folder / "session.json", {"is_model": False, "launched": True, "completed_cli": False,
            "completed_controller": True, "model_sessions": 0,
            "launch_note": "Local deterministic controller only; NO CLI/model launched",
            "wall_seconds": elapsed, "budget_charged_seconds": elapsed, "timeout": False, "errors": [],
            "overhead": {"render_seconds": 0, "reconciliation_seconds": 0},
            "shared_fixture_capture_seconds": fixture["capture_seconds"],
            "usage_for_scoring": None, "modelUsage": None, "raw_total_cost_usd": None})
        cell = {**case, "arm": "D_ALWAYS_RECHECK", "opaque_id": identifier, "id": identifier}
        rows.append(score(cell, folder, settings, is_model=False))
    result = {"is_model": False, "execution_state": "completed", "model_calls": 0,
              "description": "Always run every permitted mandatory computable check; repair numeric component/configuration if functional test fails; recheck; shared conventional gate; physical unknown retained",
              "wall_seconds": time.perf_counter() - total_start, "per_run": rows,
              "by_family": [{"family": family, **aggregate([r for r in rows if r["family"] == family], settings)} for family in settings["families"]],
              "summary": {"cases": len(rows), "supported_delivery": sum(r["supported_delivery"] for r in rows),
                          "protocol_correct_disposition": sum(r["protocol_correct_disposition"] for r in rows),
                          "unsupported_committed_release": sum(r["unsupported_committed_release"] for r in rows),
                          "checks": sum(r["checks"] for r in rows)}}
    write_json(destination / "results.json", result)
    print(result["summary"])


if __name__ == "__main__":
    main()
