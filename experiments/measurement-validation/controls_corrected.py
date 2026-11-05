"""Post-study validation variant of expansion/controls.py; not the empirical implementation.

The original function bodies are retained except for an evidence-admission predicate.
See runs/run-002/patch-provenance.json for the original digest and an exact diff.
The label contract comes from expansion/checker.py and domain.capture_check:
compile produces compile scope; functional produces real-local-functional-v2.
There is no local producer for physical-fit or arbitrary check/scope labels.
"""
import json
import time

CHECK_SCOPES = {"compile": "compile", "functional": "real-local-functional-v2"}


def label_provenance_error(evidence):
    """Return a label/provenance defect, or None. This does not authenticate evidence.

    stdout is authoritative. The optional cached parsed output must not contradict
    its labels. Complete captured records must identify the commanded check in
    command_template; this is the existing local capture format, not a new model tool.
    """
    if not isinstance(evidence, dict):
        return "record_not_object"
    check, scope = evidence.get("check"), evidence.get("scope")
    if not isinstance(check, str) or check not in CHECK_SCOPES:
        return "unknown_or_missing_check"
    if scope != CHECK_SCOPES[check]:
        return "check_scope_mismatch"
    raw = evidence.get("raw")
    if not isinstance(raw, dict):
        return "missing_raw_provenance"
    try:
        output = json.loads(raw["stdout"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return "unreadable_stdout"
    if not isinstance(output, dict) or output.get("check") != check or output.get("scope") != scope:
        return "stdout_label_mismatch"
    if "parsed" in raw:
        cached = raw["parsed"]
        if not isinstance(cached, dict) or cached.get("check") != check or cached.get("scope") != scope:
            return "cached_label_mismatch"
    command = raw.get("command_template")
    if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
        return "missing_or_malformed_command_provenance"
    if command.count("--check") != 1:
        return "ambiguous_or_missing_command_check"
    index = command.index("--check")
    if index + 1 >= len(command) or command[index + 1] != check:
        return "command_check_mismatch"
    return None


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
            valid = (label_provenance_error(evidence) is None and
                     isinstance(raw, dict) and raw.get("subject_sha256") == evidence["subject_sha256"] and
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
