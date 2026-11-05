"""Corrected prospective gate, SAME function for G and P.

Semantics informed by measurement-validation/controls_corrected.py; no historic
control imported. Functional label/scope and raw/parsed/command coherence mandatory.
"""
import json
import time
from .common import canonical, sha, subject


def admitted(record, context):
    try:
        if not isinstance(record, dict) or record.get("complete") is not True or record["check"] != "functional":
            return False
        if record["scope"] != context["contract"]["scope"]:
            return False
        raw = record["raw"]
        parsed = json.loads(raw["stdout"])
        if not isinstance(parsed, dict) or raw.get("parsed") != parsed or raw.get("timed_out") is not False:
            return False
        for name in ("check", "scope", "subject_sha256", "outcome"):
            if parsed.get(name) != record[name]:
                return False
        command = raw["command_template"]
        if not isinstance(command, list) or not all(isinstance(p, str) for p in command):
            return False
        for flag, expected in (("--check", "functional"), ("--case", context["contract"]["case"]),
                               ("--subject", record["subject_sha256"])):
            if command.count(flag) != 1 or command[command.index(flag) + 1] != expected:
                return False
        result = parsed["adapter_result"]
        if (parsed["case"] != context["contract"]["case"] or result["case"] != parsed["case"]
                or type(result["tests_run"]) is not int
                or result["tests_run"] != context["contract"]["tests_run"] or result["skipped"] != []):
            return False
        if any(type(result[k]) is not int or result[k] < 0 for k in ("failure_count", "error_count")):
            return False
        if record["outcome"] not in ("pass", "fail"):
            return False
        code = 0 if record["outcome"] == "pass" else 1
        if type(raw["exit_code"]) is not int or raw["exit_code"] != code or parsed["adapter_returncode"] != code:
            return False
        if result["success"] is not (code == 0):
            return False
        if code == 0 and (result["failure_count"] != 0 or result["error_count"] != 0):
            return False
        if code == 1 and result["failure_count"] + result["error_count"] <= 0:
            return False
        adapter_rows = [json.loads(line[12:]) for line in parsed["adapter_stdout"].splitlines()
                        if line.startswith("RESULT_JSON ")]
        if adapter_rows != [result]:
            return False
        return (record["subject_sha256"] == sha(canonical(record["subject_manifest"]))
                and record["subject_manifest"] == subject(context["full_manifest"])
                and record["binding"] == context["binding"])
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def reconcile(context):
    started = time.monotonic()
    relevant = [r for r in context["evidence"] if admitted(r, context)]
    failure = any(r["outcome"] == "fail" for r in relevant)
    supported = not failure and any(r["outcome"] == "pass" for r in relevant)
    return {"technical": "contradicted" if failure else "supported" if supported else "unknown",
            "applicable_ids": [r["id"] for r in relevant],
            "conflict_rule": "Any applicable fail blocks; no last-writer or unrecorded conflict resolution",
            "runtime_seconds": time.monotonic() - started}


def gate(context):
    started = time.monotonic()
    technical = reconcile(context)
    authorized = context["contract"].get("release_authorized") is True
    preserved = (all(context["full_manifest"].get(k) == v for k, v in context["contract"]["preserve"].items())
                 and set(context["full_manifest"]) == set(subject(context["full_manifest"])) | set(context["contract"]["preserve"]))
    allowed = authorized and preserved and technical["technical"] == "supported"
    return {"allowed": allowed, "technical": technical["technical"],
            "reason": "authorized_supported" if allowed else "authorization_revoked" if not authorized
            else "protected_file_changed" if not preserved else "unsupported",
            "runtime_seconds": time.monotonic() - started}
