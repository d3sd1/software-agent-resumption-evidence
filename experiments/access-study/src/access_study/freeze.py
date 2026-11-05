"""Prospective freeze builder. Implemented for coordinator use; no automatic freeze."""
from pathlib import Path
import math
from .common import ROOT, canonical, sha, read, write, inventory, copy_verified, settings, source_hashes
from .policies import verify_preparation
from .cli_bridge import system_prompt


def build(prepared, validation, tests, preflight, review, output):
    prepared, validation = Path(prepared), Path(validation)
    receipt = verify_preparation(prepared)
    evidence = read(validation / "validation.json")
    test_receipt, neutral, approval = read(tests), read(preflight), read(review)
    cfg = settings()
    if (not evidence.get("passed") or evidence["source_hashes"] != source_hashes()
            or evidence["preparation_sha256"] != sha((prepared / "preparation.json").read_bytes())):
        raise RuntimeError("Matching local validation required")
    actual = inventory(validation)
    actual.pop("validation.json", None)
    if actual != evidence["artifact_hashes"]:
        raise RuntimeError("Validation artifacts changed")
    if not test_receipt.get("passed") or test_receipt.get("source_hashes") != source_hashes():
        raise RuntimeError("Current executed unit-test receipt required")
    if (neutral.get("kind") != "neutral_transport" or neutral.get("owner") != "coordinator"
            or neutral.get("passed") is not True or type(neutral.get("sessions")) is not int
            or not 1 <= neutral["sessions"] <= cfg["preflight_cap"]
            or not isinstance(neutral.get("model_identity"), str) or not neutral["model_identity"].strip()
            or not isinstance(neutral.get("cli_version"), str) or not neutral["cli_version"].strip()
            or type(neutral.get("wall_seconds")) not in (int, float)
            or not math.isfinite(neutral["wall_seconds"]) or neutral["wall_seconds"] < 0):
        raise RuntimeError("Coordinator-observed neutral transport receipt required; never infer identity")
    raw_path = Path(preflight).parent / neutral["raw_events_path"]
    if not raw_path.resolve().is_relative_to(Path(preflight).parent.resolve()):
        raise RuntimeError("Preflight raw path escaped receipt directory")
    raw = raw_path.read_bytes()
    if sha(raw) != neutral["raw_events_sha256"]:
        raise RuntimeError("Neutral stream digest differs")
    import json
    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    results = [e for e in events if e.get("type") == "result"]
    if not results or any(set(e.get("modelUsage", {})) != {neutral["model_identity"]} for e in results):
        raise RuntimeError("Preflight raw model identity missing/incoherent")
    if any(e.get("tools") or e.get("permission_denials") or e.get("is_error") for e in events):
        raise RuntimeError("Preflight exposed tools or errors")
    if (approval.get("implementation_approved") is not True or approval.get("source_hashes") != source_hashes()
            or approval.get("preparation_sha256") != sha((prepared / "preparation.json").read_bytes())
            or approval.get("validation_sha256") != sha((validation / "validation.json").read_bytes())):
        raise RuntimeError("Second implementation review bound to these inputs required")
    overhead = receipt["shared_seconds"] + neutral["wall_seconds"]
    capacity = cfg["planned_sessions"] / cfg["workers"] * cfg["session_seconds"]
    if capacity + overhead >= cfg["global_seconds"]:
        raise RuntimeError("Capacity plus measured shared/preflight overhead exceeds envelope")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    copy_verified(prepared, output / "prepared", inventory(prepared))
    for name in source_hashes():
        dest = output / "implementation" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((ROOT / name).read_bytes())
    for name in ("protocol-v1.md", "protocol-review-1.md"):
        (output / name).write_bytes((ROOT / name).read_bytes())
    for name, source in (("unit-tests.json", tests), ("neutral-preflight.json", preflight),
                         ("second-review.json", review), ("local-validation.json", validation / "validation.json")):
        (output / name).write_bytes(Path(source).read_bytes())
    (output / "neutral-stream.jsonl").write_bytes(raw)
    prompts = {}
    for row in evidence["controls"]:
        if row["policy"] != "reference":
            continue
        cell = row["cell"]
        key = "__".join((cell["case"], cell["state"], cell["arm"]))
        prompt = (validation / row["path"] / "prompt.txt").read_bytes()
        if key in prompts and prompts[key] != sha(prompt):
            raise RuntimeError("Prompt parity changed")
        prompts[key] = sha(prompt)
        path = output / "prompts" / (key + ".txt")
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(prompt)
    (output / "system-prompt.txt").write_text(system_prompt())
    manifest = {"schema": "access-study-frozen-v1", "source_hashes": source_hashes(),
                "files": inventory(output), "planned": read(prepared / "assignments.json"),
                "prompt_hashes": prompts, "system_prompt_sha256": sha(system_prompt().encode()),
                "shared_preflight_seconds": overhead, "model_identity": neutral["model_identity"],
                "cli_version": neutral["cli_version"], "model_requested": "inherited; no override",
                "participant_sessions": 0, "consent": "Freeze is not authorization to call models"}
    write(output / "manifest.json", manifest)
    for path in output.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    return manifest


def verify(folder):
    folder = Path(folder)
    manifest = read(folder / "manifest.json")
    files = inventory(folder)
    files.pop("manifest.json", None)
    if files != manifest["files"] or source_hashes() != manifest["source_hashes"]:
        raise RuntimeError("Frozen files or executable source changed")
    if sha(system_prompt().encode()) != manifest["system_prompt_sha256"]:
        raise RuntimeError("System prompt differs from freeze")
    cfg = settings()
    if len(manifest["planned"]) != 160 or cfg["workers"] != 2 or cfg["action_cap"] != 32:
        raise RuntimeError("Unexpected design or budget")
    return manifest
