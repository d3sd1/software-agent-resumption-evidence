"""Local instrument. Single gate, immutable event snapshots, charged failed actions."""
import copy
import json
from pathlib import Path
import shutil
import time
from .common import canonical, sha, read, write, inventory, subject, copy_verified, verify_tree, settings, append, stamp
from .gate import gate, reconcile
from .checker import check
from .prepare import COMMON


TOOLS = {"list_context", "read_context", "run_check", "restore_verified", "release", "finish"}


class Harness:
    def __init__(self, prepared, cell, folder, deadline=None, precreated=False):
        self.started = time.monotonic()
        self.cfg = settings()
        self.deadline = deadline or self.started + self.cfg["session_seconds"]
        self.cell = cell
        self.folder = Path(folder)
        if precreated:
            if not self.folder.is_dir() or {p.name for p in self.folder.iterdir()} != {"slot-start.json"}:
                raise RuntimeError("Precreated slot must contain only its start receipt")
        else:
            self.folder.mkdir(parents=True, exist_ok=False)
        self.case_dir = Path(prepared) / "cases" / cell["case"]
        self.case = read(self.case_dir / "case.json")
        self.start_dir = self.case_dir / "states" / cell["state"]
        self.state = read(self.start_dir / "state.json")
        self.workspace = self.folder / "workspace"
        copy_verified(self.start_dir / "initial", self.workspace, self.state["full_manifest"])
        self.actions = 0
        self.finished = False
        self.previous = None
        self.seen = set()
        self.commits = []
        self.ledger = {"automatic": {"reads": [], "bytes": 0},
                       "retrieval": {"calls": 0, "documents": 0, "payload_bytes": 0,
                                     "document_bytes": 0, "unique_document_bytes": 0,
                                     "repeated_documents": 0, "errors": 0},
                       "response_bytes": 0, "gates": [], "checks": []}
        self.ledger["initialization_seconds"] = time.monotonic() - self.started
        rendering_started = time.monotonic()
        names = ["history.json", "contract.json", "dependencies.json"]
        if cell["arm"] == "P":
            names = self.cfg["document_names"]
        acquired = {}
        for name in names:
            raw = (self.start_dir / "documents" / name).read_bytes()
            acquired[name] = json.loads(raw)
            self.ledger["automatic"]["reads"].append({"name": name, "bytes": len(raw)})
            self.ledger["automatic"]["bytes"] += len(raw)
            append(self.folder / "automatic-acquisition.jsonl", {"name": name, "bytes": len(raw),
                                                                "sha256": sha(raw), "at": stamp()})
        historical = acquired["history.json"]["evidence"][0]
        narrative = ("Predecessor handoff: the selected focused functional suite passed on executable manifest "
                     + historical["subject_sha256"] + ". The check label is functional and scope is "
                     + historical["scope"] + ". This is a historical observation, not a claim of current applicability "
                     "or unrestricted correctness. The complete raw outcome and binding are in history.json. "
                     "Compare workspace.json executable entries (not its whole-release digest) with that record; "
                     "contract.json specifies authorization/protected files and dependencies.json binds the test and environment. "
                     "A documentation-only full-release change can preserve executable identity. If executable entries differ, "
                     "restore_verified can recover exactly the verified executable state without changing the note. "
                     "You can recheck when evidence is insufficient. Check for applicable contradictions before release. ")
        self.prompt = COMMON + narrative
        if cell["arm"] == "P":
            projection = reconcile({"full_manifest": acquired["workspace.json"]["full_manifest"],
                                    "contract": acquired["contract.json"],
                                    "binding": acquired["dependencies.json"],
                                    "evidence": acquired["history.json"]["evidence"]})
            self.ledger["automatic"]["reconciliation_seconds"] = projection.pop("runtime_seconds")
            self.ledger["automatic"]["projection"] = projection
            self.prompt += "Derived current-applicability projection (not an independent check): " + canonical(projection).decode()
        self.ledger["automatic"]["runtime_seconds"] = time.monotonic() - rendering_started
        self.ledger["automatic"]["derived_output_bytes"] = len(canonical(self.ledger["automatic"]["projection"])) if cell["arm"] == "P" else 0
        self.ledger["automatic"]["cache_policy"] = self.cfg["cache_policy"]
        self.ledger["automatic"]["initial_prompt_bytes"] = len(self.prompt.encode())
        write(self.folder / "initialization.json", {"cell": cell, "ledger": self.ledger,
                                                   "initial_prompt_sha256": sha(self.prompt.encode())})
        (self.folder / "prompt.txt").write_text(self.prompt)

    def context(self):
        return copy.deepcopy({"full_manifest": inventory(self.workspace), "contract": self.state["contract"],
                              "binding": self.state["binding"], "evidence": self.state["evidence"]})

    def snapshot(self, context):
        key = sha(canonical(context["full_manifest"]))
        dest = self.folder / "snapshots" / key
        if dest.exists():
            verify_tree(dest, context["full_manifest"])
        else:
            copy_verified(self.workspace, dest, context["full_manifest"])
            for file in dest.rglob("*"):
                if file.is_file():
                    file.chmod(0o444)
        return key

    def validate(self, tool, args):
        if tool not in TOOLS or not isinstance(args, dict):
            raise ValueError("Unknown action or non-object arguments")
        keys = set(args)
        if tool in ("list_context", "restore_verified", "release") and keys:
            raise ValueError("This action takes no arguments")
        if tool == "read_context":
            if self.cell["regime"] == "bundled" and keys:
                raise ValueError("Bundled read_context takes no arguments")
            if self.cell["regime"] == "distributed" and (keys != {"name"} or args["name"] not in self.cfg["document_names"]):
                raise ValueError("Distributed read_context requires one directory name")
        if tool == "run_check" and args != {"check": "functional"}:
            raise ValueError("Only the functional check is allowed")
        if tool == "finish":
            if (keys != {"technical", "disposition", "release_id", "reason"}
                    or args["technical"] not in ("supported", "unsupported")
                    or args["disposition"] not in ("delivered", "hold")
                    or not isinstance(args["reason"], str) or not args["reason"].strip()
                    or not (args["release_id"] is None or isinstance(args["release_id"], str))):
                raise ValueError("Invalid structured final assertion")

    def call(self, tool, args, raw_action=None):
        if self.finished:
            raise RuntimeError("Already finished")
        if self.actions >= self.cfg["action_cap"] or time.monotonic() >= self.deadline:
            raise TimeoutError("Action/deadline envelope exhausted before dispatch")
        self.actions += 1
        before = self.context()
        snapshot = self.snapshot(before)
        started = time.monotonic()
        error = False
        validation_error = False
        commit = None
        fatal = None
        retrieval = tool == "read_context"
        if retrieval:
            self.ledger["retrieval"]["calls"] += 1
        try:
            try:
                self.validate(tool, args)
            except (ValueError, TypeError) as exc:
                validation_error = True
                raise ValueError(str(exc)) from exc
            if tool == "list_context":
                result = {"regime": self.cell["regime"], "documents": [
                    {"name": name, "bytes": (self.start_dir / "documents" / name).stat().st_size}
                    for name in self.cfg["document_names"]],
                    "read_rule": "Use no arguments to get all documents" if self.cell["regime"] == "bundled"
                    else "Use name to request exactly one document"}
            elif retrieval:
                names = self.cfg["document_names"] if self.cell["regime"] == "bundled" else [args["name"]]
                documents = [{"name": name, "content": (self.start_dir / "documents" / name).read_text()}
                             for name in names]
                result = {"documents": documents}
                if len(canonical(result)) > self.cfg["max_response_bytes"]:
                    raise RuntimeError("Transport response limit exceeded; no truncated delivery")
                ledger = self.ledger["retrieval"]
                ledger["payload_bytes"] += len(canonical(result))
                for doc in documents:
                    size = len(doc["content"].encode())
                    ledger["documents"] += 1
                    ledger["document_bytes"] += size
                    if doc["name"] in self.seen:
                        ledger["repeated_documents"] += 1
                    else:
                        ledger["unique_document_bytes"] += size
                    self.seen.add(doc["name"])
            elif tool == "restore_verified":
                verified = self.case["snapshots"]["after"]
                verify_tree(self.case_dir / "after", verified)
                shutil.rmtree(self.workspace / "source")
                source_manifest = {k[len("source/"):]: v for k, v in verified.items() if k.startswith("source/")}
                copy_verified(self.case_dir / "after/source", self.workspace / "source", source_manifest)
                after = inventory(self.workspace)
                if any(after.get(k) != v for k, v in before["contract"]["preserve"].items()):
                    raise RuntimeError("Restore modified protected files")
                result = {"restored": True, "executable_manifest": subject(after), "note_preserved": True}
            elif tool == "run_check":
                evidence = check(self.workspace, self.cell["case"], self.case_dir / "tests/adapter.py",
                                 self.state["binding"], self.folder / "checks" / f"check-{self.actions:03}", self.deadline)
                self.state["evidence"].append(evidence)
                self.ledger["checks"].append({"id": evidence["id"], "runtime_seconds": evidence["runtime_seconds"],
                                               "outcome": evidence["outcome"]})
                result = {"evidence": evidence}
                if not evidence["complete"]:
                    fatal = "check_infrastructure_or_timeout"
                    error = True
            elif tool == "release":
                result = gate(before)
                self.ledger["gates"].append(result)
                if result["allowed"]:
                    commit = f"release-{self.actions:03}-{snapshot}"
                    copy_verified(self.workspace, self.folder / "releases" / commit, before["full_manifest"])
                    self.commits.append(commit)
                    result["release_id"] = commit
            else:
                self.finished = True
                result = {"recorded": True}
        except Exception as exc:
            error = True
            result = {"error": type(exc).__name__ + ": " + str(exc)}
            if not validation_error:
                fatal = "instrument_error"
        if retrieval and error:
            self.ledger["retrieval"]["errors"] += 1
        if len(canonical(result)) > self.cfg["max_response_bytes"]:
            write(self.folder / f"oversized-{self.actions}.json", result)
            result = {"error": "response exceeded limit; full response retained locally, not delivered"}
            error, fatal = True, "response_limit"
        if time.monotonic() > self.deadline:
            error, fatal = True, "session_deadline"
        self.ledger["response_bytes"] += len(canonical(result))
        event = {"index": self.actions, "at": stamp(), "tool": tool, "arguments": args,
                 "raw_action": raw_action, "snapshot": snapshot, "context": before,
                 "result": result, "error": error, "validation_error": validation_error,
                 "fatal": fatal, "commit": commit, "seconds": time.monotonic() - started,
                 "previous_sha256": self.previous}
        event["event_sha256"] = sha(canonical(event))
        append(self.folder / "events.jsonl", event)
        self.previous = event["event_sha256"]
        # Preserve post-action state even when the bridge cannot return feedback.
        after = self.context()
        self.snapshot(after)
        write(self.folder / "states" / f"{self.actions:03}.json", after)
        return result, error, fatal

    def close(self, termination):
        metadata = {"cell": self.cell, "termination": termination, "finished": self.finished,
                    "actions": self.actions, "ledger": self.ledger, "wall_seconds": time.monotonic() - self.started,
                    "last_event_sha256": self.previous}
        write(self.folder / "instrument.json", metadata)
        return metadata
