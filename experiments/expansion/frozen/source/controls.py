"""Original small dependency-withdrawal adapter plus shared conventional shadow gate."""
import json
import time


def reconciliation(context):
    started = time.perf_counter()
    scopes = context["contract"]["required_scopes"]
    outcomes = {scope: [] for scope in scopes}
    stale, incomplete = [], []
    for evidence in context["evidence"]:
        if not isinstance(evidence, dict) or not evidence.get("complete"):
            incomplete.append(evidence.get("id") if isinstance(evidence, dict) else None)
            continue
        try:
            raw = json.loads(evidence["raw"]["stdout"])
            valid = (isinstance(raw, dict) and raw.get("subject_sha256") == evidence["subject_sha256"] and
                     raw.get("scope") == evidence["scope"] and raw.get("outcome") == evidence["outcome"] and
                     raw.get("check") == evidence["check"] and
                     evidence["raw"]["exit_code"] == {"pass": 0, "fail": 1}.get(evidence["outcome"]))
        except (KeyError, TypeError, json.JSONDecodeError):
            valid = False
        if not valid:
            incomplete.append(evidence.get("id"))
            continue
        if (evidence["subject_sha256"] != context["candidate_sha256"] or
                evidence["criterion_version"] != context["contract"]["version"] or
                evidence["dependencies"] != context["dependencies"]):
            stale.append(evidence["id"])
            continue
        if evidence["scope"] in outcomes:
            outcomes[evidence["scope"]].append(evidence["outcome"])
    if any("fail" in values for values in outcomes.values()):
        state, reason = "contradicted", "applicable_failure"
    elif all("pass" in values for values in outcomes.values()):
        state, reason = "supported", "all_required_scopes_supported"
    elif incomplete or "physical-fit" in scopes:
        state, reason = "unknown", "missing_or_unobservable_required_evidence"
    elif stale:
        state, reason = "stale", "subject_or_dependency_changed"
    else:
        state, reason = "unknown", "required_scope_unobserved"
    return {"technical_state": state, "reason": reason, "withdrawn_ids": stale,
            "incomplete_ids": incomplete, "served_pass": True if state == "supported" else None,
            "runtime_seconds": time.perf_counter() - started}


def gate(context):
    started = time.perf_counter()
    technical = reconciliation(context)
    return {"allowed": context["policy"]["release"] and technical["technical_state"] == "supported",
            "reason": technical["reason"] if context["policy"]["release"] else "authorization_revoked",
            "technical": technical, "runtime_seconds": time.perf_counter() - started}
