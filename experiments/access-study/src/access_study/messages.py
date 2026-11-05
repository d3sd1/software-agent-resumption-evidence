"""Newly supplied UTF-8 content, with writer closure bound to the final receipt."""
import hashlib
import json
from pathlib import Path
from .common import append, canonical, sha, stamp


def response_content(tool, result, error):
    return canonical({"tool_result": {"tool": tool, "is_error": error, "result": result},
                      "instruction": "Choose the next single JSON action; current task/policy unchanged."}).decode()


class MessageLedger:
    def __init__(self, folder, mode="client_supply"):
        self.path = Path(folder) / "message-ledger.jsonl"
        # An explicitly created empty log can close at zero. An absent/lost log cannot.
        with self.path.open("xb"):
            pass
        self.mode = mode
        self.index = 0
        self.records = 0
        self.deliveries = 0
        self.previous = None
        self.hasher = hashlib.sha256()
        self.closure = None

    def _record(self, event):
        if self.closure is not None:
            raise RuntimeError("Message ledger already closed")
        event["previous_sha256"] = self.previous
        event["record_sha256"] = sha(canonical(event))
        append(self.path, event)
        self.hasher.update(canonical(event) + b"\n")
        self.previous = event["record_sha256"]
        self.records += 1

    def begin(self, category, content):
        if self.closure is not None:
            raise RuntimeError("Message ledger already closed")
        if not isinstance(content, str):
            raise TypeError("Count actual rendered strings, never reconstructed objects")
        self.index += 1
        self._record({"event": "content", "id": self.index, "at": stamp(), "category": category,
                      "content": content, "utf8_bytes": len(content.encode("utf-8")),
                      "sha256": sha(content.encode("utf-8")), "mode": self.mode})
        return self.index

    def end(self, index, status):
        if status not in ("supplied_to_client", "not_supplied", "unknown", "reference_rendered"):
            raise ValueError("Unknown delivery status")
        self._record({"event": "delivery", "id": index, "status": status, "at": stamp()})
        self.deliveries += 1

    def reference(self, category, content):
        index = self.begin(category, content)
        self.end(index, "reference_rendered")

    def close(self):
        """Bind writer-side counts/hash, not a re-count of possibly truncated disk data."""
        if self.closure is None:
            self.closure = {"schema": "message-ledger-closure-v1", "closed": True,
                            "record_count": self.records, "message_count": self.index,
                            "delivery_count": self.deliveries, "last_record_sha256": self.previous,
                            "log_sha256": self.hasher.hexdigest(), "mode": self.mode}
        return dict(self.closure)


def measure(folder, closure=None):
    """Return unknown totals on loss/corruption; retain any structurally verified prefix.

    A caller must pass the writer closure obtained from its hash-verified lifecycle
    receipt (or the explicit local control receipt). A free-standing ledger cannot
    certify its own completeness. No absent_known escape hatch is provided.
    """
    path = Path(folder) / "message-ledger.jsonl"
    errors, content, delivery = [], {}, {}
    raw = None
    previous, records = None, 0
    try:
        raw = path.read_bytes()
    except OSError as exc:
        errors.append("message_log_missing_or_unreadable: " + type(exc).__name__)
    if raw is not None:
        for line in raw.splitlines(keepends=True):
            try:
                if not line.endswith(b"\n"):
                    raise ValueError("Unfinished message record")
                event = json.loads(line)
                stored = event.pop("record_sha256")
                if event["previous_sha256"] != previous or sha(canonical(event)) != stored:
                    raise ValueError("Message record chain mismatch")
                index = event["id"]
                if type(index) is not int or index < 1:
                    raise ValueError("Invalid message identifier")
                if event["event"] == "content":
                    if index != len(content) + 1 or sha(event["content"].encode("utf-8")) != event["sha256"]:
                        raise ValueError("Content identity mismatch")
                    if type(event["utf8_bytes"]) is not int or len(event["content"].encode("utf-8")) != event["utf8_bytes"]:
                        raise ValueError("UTF-8 length mismatch")
                    if not isinstance(event["category"], str) or not isinstance(event["mode"], str):
                        raise ValueError("Invalid content category/mode")
                    content[index] = event
                elif event["event"] == "delivery":
                    if index in delivery or index not in content:
                        raise ValueError("Invalid delivery sequence")
                    if event["status"] not in ("supplied_to_client", "not_supplied", "unknown", "reference_rendered"):
                        raise ValueError("Invalid delivery status")
                    delivery[index] = event["status"]
                else:
                    raise ValueError("Unknown message record kind")
                previous = stored
                records += 1
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                errors.append("message_prefix_integrity: " + str(exc))
                break
    required_counts = ("record_count", "message_count", "delivery_count")
    valid_closure = (isinstance(closure, dict) and closure.get("schema") == "message-ledger-closure-v1"
                     and closure.get("closed") is True
                     and all(type(closure.get(k)) is int and closure[k] >= 0 for k in required_counts))
    if not valid_closure:
        errors.append("missing_or_invalid_message_closure")
    elif (raw is None or closure.get("log_sha256") != sha(raw)
          or closure["record_count"] != records or closure["message_count"] != len(content)
          or closure["delivery_count"] != len(delivery) or closure.get("last_record_sha256") != previous
          or any(c["mode"] != closure.get("mode") for c in content.values())):
        errors.append("message_closure_count_or_hash_mismatch")
    categories = {}
    unknown = 0
    for index, item in content.items():
        category = categories.setdefault(item["category"], {"known_bytes": 0, "unknown_messages": 0,
                                                           "supplied_messages": 0, "not_supplied_messages": 0})
        status = delivery.get(index, "unknown")
        if status in ("supplied_to_client", "reference_rendered"):
            category["known_bytes"] += item["utf8_bytes"]
            category["supplied_messages"] += 1
        elif status == "not_supplied":
            category["not_supplied_messages"] += 1
        else:
            category["unknown_messages"] += 1
            unknown += 1
    prefix_bytes = sum(c["known_bytes"] for c in categories.values())
    accounted = not errors and unknown == 0
    return {"bytes": prefix_bytes if accounted else None, "fully_accounted": accounted,
            "closure_verified": not errors, "audit_errors": errors, "categories": categories,
            "delivery_unknown": unknown, "known_prefix_bytes": prefix_bytes,
            "record_count_observed": records, "message_count_observed": len(content),
            "modes": sorted({c["mode"] for c in content.values()}),
            "boundary": "New system argument and user/driver content supplied to CLI, once; excludes role framing, assistant outputs, auth, provider internals and accumulated-history retransmission"}
