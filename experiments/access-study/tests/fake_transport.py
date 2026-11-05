"""SYNTHETIC transport unit helper. This is NOT a model, provider or public case."""
import json
import sys

scenario = sys.argv[1]
identity = "synthetic-unit-identity"
print(json.dumps({"type": "system", "subtype": "init", "model": identity,
                  "tools": ["unexpected"] if scenario == "native" else []}), flush=True)
for index, line in enumerate(sys.stdin):
    incoming = json.loads(line)
    if scenario == "deadline":
        # Wait for parent to close input; no model or network exists.
        for _ in sys.stdin:
            pass
        break
    finish = {"tool": "finish", "arguments": {"technical": "unsupported", "disposition": "hold",
                                               "release_id": None, "reason": "synthetic unit"}}
    action = {"tool": "list_context", "arguments": {}} if index == 0 or scenario == "cap" else finish
    if scenario in ("deliver", "unsafe_then_deliver"):
        step = index - (1 if scenario == "unsafe_then_deliver" else 0)
        if step < 0:
            action = {"tool": "release", "arguments": {}}
        elif step == 0:
            action = {"tool": "restore_verified", "arguments": {}}
        elif step == 1:
            action = {"tool": "release", "arguments": {}}
        else:
            response = json.loads(incoming["message"]["content"])["tool_result"]["result"]
            action = {"tool": "finish", "arguments": {"technical": "supported", "disposition": "delivered",
                      "release_id": response["release_id"], "reason": "synthetic delivery unit"}}
    text = "not json" if scenario == "invalid" and index == 0 else json.dumps(action)
    model = "synthetic-other" if scenario == "identity" else identity
    print(json.dumps({"type": "result", "result": text, "modelUsage": {model: {}},
                      "model_usage_since_last_result": {model: {"inputTokens": 1, "outputTokens": 1,
                      "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0}},
                      "is_error": scenario == "quota"}), flush=True)
