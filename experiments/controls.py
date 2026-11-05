"""Original small adapters of established evidence-withdrawal and CI gating ideas.

Not copied Tether source; scope and authorization annotations are study additions.
The offline scorer must never import this module.
"""
import time


def reconcile(candidate_hash, contract, deps, evidence):
    started = time.perf_counter()
    applicable = []
    stale = []
    for item in evidence:
        if (item["subject_sha256"] != candidate_hash or
                item["criterion_version"] != contract["version"] or item["dependencies"] != deps):
            stale.append(item["id"])
        elif item["scope"] == contract["scope"]:
            applicable.append(item)
    if any(e["outcome"] == "fail" for e in applicable):
        state, reason = "contradicted", "applicable_failure"
    elif any(e["outcome"] == "pass" for e in applicable):
        state, reason = "supported", "applicable_pass"
    elif stale:
        state, reason = "stale", "dependency_or_subject_changed"
    else:
        state, reason = "unknown", "required_scope_unobserved"
    return {"technical_state": state, "reason": reason,
            "withdrawn_ids": stale,
            "served_pass": True if state == "supported" else None,
            "runtime_seconds": time.perf_counter() - started}


def gate(candidate_hash, contract, deps, evidence, policy):
    """The identical predicate and implementation is used by both G and P."""
    started = time.perf_counter()
    technical = reconcile(candidate_hash, contract, deps, evidence)
    allowed = policy["release"] and technical["technical_state"] == "supported"
    return {"allowed": allowed,
            "reason": ("authorization_revoked" if not policy["release"] else technical["reason"]),
            "technical": technical, "runtime_seconds": time.perf_counter() - started}
