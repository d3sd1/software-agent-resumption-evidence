"""Serialize phase-separated evidence, never infer unexecuted expansion outcomes."""
from common import ROOT, digest, read_json, stamp, write_json


def main():
    original = read_json(ROOT / "results" / "pilot_results.json")
    revised = read_json(ROOT / "results" / "pilot_reanalysis.json")
    expansion_path = ROOT / "results" / "expanded_results.json"
    if not expansion_path.exists():
        config = read_json(ROOT / "expansion" / "config-v2.json")
        write_json(expansion_path, {
            "schema_version": 2, "phase": "diagnostic-expansion", "execution_state": "unassigned",
            "planned_sessions": config["planned_sessions"], "assigned": 0, "launched": 0,
            "action_exposed": 0, "complete_structured": 0,
            "stop_reason": "Not launched: direct user authorization for increased budget, expanded implementation, freeze and corrected-bridge preflight remain pending",
            "freeze_manifest": None, "per_run": [], "per_family_arm": [],
            "deterministic_reference": {"is_model": False, "execution_state": "not_implemented", "per_run": []},
            "limitations": ["Specification only; no expanded model sessions or five-repetition metrics exist",
                            "No confirmatory or efficacy claim", "B4 not implemented or compared"]})
    expansion = read_json(expansion_path)
    summary = {"schema_version": 2, "created_at": stamp(), "phases_are_not_pooled": True,
               "pilot": {"source": "results/pilot_results.json",
                         "source_sha256": digest((ROOT / "results" / "pilot_results.json").read_bytes()),
                         "reanalysis_source": "results/pilot_reanalysis.json",
                         "source_snapshot": "snapshots/pilot-v1/source",
                         "assigned": revised["assigned"], "launched": revised["launched"],
                         "complete_structured": revised["complete_structured"],
                         "supported_delivery": sum(r["supported_delivery"] for r in revised["per_run"]),
                         "protocol_correct_disposition": sum(r["protocol_correct_disposition"] for r in revised["per_run"]),
                         "unsupported_committed_release": sum(r["unsupported_committed_release"] for r in revised["per_run"]),
                         "original_accepted_completion": sum(r["accepted_completion"] for r in original["per_run"]),
                         "accepted_completion_alias": "protocol_correct_disposition, not delivery",
                         "by_arm": revised["by_arm"]},
               "expansion": {"source": "results/expanded_results.json", "schema": "expansion/expanded-results.schema.json",
                             "execution_state": expansion["execution_state"], "planned_sessions": expansion["planned_sessions"],
                             "assigned": expansion["assigned"], "launched": expansion["launched"],
                             "action_exposed": expansion["action_exposed"],
                             "complete_structured": expansion["complete_structured"],
                             "per_family_arm": expansion["per_family_arm"],
                             "by_arm": expansion.get("by_arm", {}),
                             "freeze_manifest": expansion.get("freeze_manifest"),
                             "deterministic_reference": expansion["deterministic_reference"]},
               "limitations": ["Pilot is descriptive feasibility, not efficacy; 14 deliveries and 14 appropriate holds",
                               "No expanded results inferred from the coordinator's requested design",
                               "No pooling pilot heterogeneity with five-seed expansion variation",
                               "Shadow gate executed in all pilot arms; enforced only G/P; cost included for all",
                               "Original raw files and source snapshot retained unchanged"]}
    write_json(ROOT / "results" / "aggregated_results.json", summary)
    print({"pilot_assigned": summary["pilot"]["assigned"],
           "pilot_supported_delivery": summary["pilot"]["supported_delivery"],
           "pilot_protocol_correct_disposition": summary["pilot"]["protocol_correct_disposition"],
           "expansion_execution_state": expansion["execution_state"], "new_model_calls": 0})


if __name__ == "__main__":
    main()
