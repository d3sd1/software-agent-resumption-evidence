"""JSON-action bridge for safe-mode CLI, which disables even explicit MCP.

A single live CLI process retains the session. The model, not rules, selects each
operation. The bridge only parses an allowlisted action and executes FixtureTools.
These are real harness operations, NOT native MCP/model function calls.
"""
import json
import os
import queue
import signal
import subprocess
import threading
import time
from common import append_json, stamp
from harness import FixtureTools
from mcp_server import TOOLS

PROTOCOL = (
    "Tool transport: JSON-action bridge, not native MCP. Native tools are disabled. "
    "For each response output EXACTLY one JSON object with keys tool and arguments, "
    "no markdown, narration, extra keys, or list. Example: "
    '{"tool":"inspect_state","arguments":{}}. '
    "The harness really executes that operation and sends its result in the next user message "
    "within this same session. You choose operations; no deterministic agent replaces you. "
    "Your final action MUST be finish. The harness ends the session after executing finish; "
    "do not generate a separate final narrative. Up to eight operations total. Available schemas: "
    + json.dumps(TOOLS, ensure_ascii=True)
)


def parse_action(text, allowed):
    action = json.loads(text)
    if not isinstance(action, dict) or set(action) != {"tool", "arguments"}:
        raise ValueError("Expected exactly tool and arguments")
    if action["tool"] not in allowed or not isinstance(action["arguments"], dict):
        raise ValueError("Action outside tool allowlist or invalid arguments")
    return action


def execute(cmd, folder, prompt, config, started):
    events = queue.Queue()
    errors = []
    timed_out = False
    deadline = started + config["session_seconds_cap"]
    tools = FixtureTools(folder, deadline=deadline)
    reader_error = []
    with (folder / "stdout.stream.jsonl").open("w", encoding="utf-8") as out, \
         (folder / "stderr.txt").open("w", encoding="utf-8") as err:
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                                   text=True, bufsize=1, cwd=folder / "workspace", start_new_session=True)
        def read_stream():
            try:
                for line in process.stdout:
                    out.write(line)
                    out.flush()
                    events.put(json.loads(line))
            except Exception as exc:
                reader_error.append(f"stdout reader: {type(exc).__name__}: {exc}")
            finally:
                events.put(None)
        thread = threading.Thread(target=read_stream, daemon=True)
        thread.start()
        def send(text):
            message = {"type": "user", "message": {"role": "user", "content": text},
                       "parent_tool_use_id": None, "session_id": ""}
            append_json(folder / "stdin.stream.jsonl", message)
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
        try:
            send(prompt)
            while not tools.state["finished"]:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    raise TimeoutError("session time cap")
                event = events.get(timeout=remaining)
                if event is None:
                    raise RuntimeError("CLI stdout closed before finish")
                if event.get("type") == "system" and event.get("subtype") == "init" and event.get("tools"):
                    raise RuntimeError("Unexpected native tools exposed")
                if event.get("type") != "result":
                    continue
                if event.get("is_error") or event.get("permission_denials"):
                    raise RuntimeError("CLI error or permission denial; no retry")
                action = parse_action(event.get("result", ""), config["tool_names"])
                append_json(folder / "bridge-actions.jsonl", {"timestamp": stamp(), "action": action,
                            "source_result_uuid": event.get("uuid"), "source_session_id": event.get("session_id")})
                if time.perf_counter() >= deadline:
                    raise TimeoutError("session time cap before dispatch")
                result, error = tools.call(action["tool"], action["arguments"])
                if "deadline_exceeded" in result:
                    raise TimeoutError(result["deadline_exceeded"])
                if "infrastructure_error" in result:
                    raise RuntimeError(result["infrastructure_error"])
                if tools.state["finished"]:
                    break
                if tools.state["executed_tools"] >= config["tool_execution_cap"]:
                    raise RuntimeError("Tool cap reached without finish; no ninth operation")
                send(json.dumps({"tool_result": {"tool": action["tool"], "is_error": error, "result": result},
                                 "instruction": "Choose the next single JSON action. Current policy and original task remain unchanged."}))
            process.stdin.close()
            process.wait(timeout=max(0.1, deadline - time.perf_counter()))
        except (TimeoutError, queue.Empty, subprocess.TimeoutExpired):
            timed_out = True
            errors.append("session timeout")
        except Exception as exc:
            errors.append(f"bridge error: {type(exc).__name__}: {exc}")
        finally:
            try:
                if not process.stdin.closed:
                    process.stdin.close()
            except BrokenPipeError:
                pass
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            thread.join(timeout=2)
            if thread.is_alive():
                errors.append("stdout reader failed to terminate")
            process.stdout.close()
    errors.extend(reader_error)
    return process.returncode, timed_out, errors


def usage_from_deltas(results):
    """Sum CLI's explicit per-result deltas; do not double-count cumulative totals."""
    names = {"input_tokens": "inputTokens", "output_tokens": "outputTokens",
             "cache_read_input_tokens": "cacheReadInputTokens",
             "cache_creation_input_tokens": "cacheCreationInputTokens"}
    if not results or all(not result.get("model_usage_since_last_result") for result in results):
        return None
    aggregates = {}
    for output, key in names.items():
        values, missing = [], False
        for result in results:
            delta = result.get("model_usage_since_last_result")
            if not isinstance(delta, dict) or not delta:
                missing = True
                continue
            for model in delta.values():
                value = model.get(key) if isinstance(model, dict) else None
                if type(value) is not int or value < 0:
                    missing = True
                else:
                    values.append(value)
        aggregates[output] = None if missing else sum(values)
    return aggregates
