"""Real local compile/functional checks; no external service or physical observations."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--check", choices=["compile", "functional"], required=True)
    parser.add_argument("--target", type=int, required=True)
    parser.add_argument("--cases", required=True)
    args = parser.parse_args()
    data = Path(args.snapshot).read_bytes()
    package = json.loads(data)
    result = {"subject_sha256": hashlib.sha256(data).hexdigest(), "check": args.check,
              "scope": "compile" if args.check == "compile" else "real-local-functional-v2"}
    source = package["source"]
    try:
        compiled = compile(source, "component.py", "exec")
    except SyntaxError as exc:
        result.update(outcome="fail", error=str(exc))
        print(json.dumps(result))
        return 1
    if args.check == "compile":
        result.update(outcome="pass", limits="Syntax compilation only; component not executed")
        print(json.dumps(result))
        return 0
    if not re.fullmatch(r"def net\(cents, offset\):\n    return cents \* (?:[0-9]{1,2}|100) // 100 \+ offset\n", source):
        result.update(outcome="fail", error="component outside bounded template")
        print(json.dumps(result))
        return 1
    namespace = {"__builtins__": {}}
    exec(compiled, namespace)
    offset = package["configuration"]["offset"]
    cases = json.loads(args.cases)
    failures = [{"cents": value, "actual": namespace["net"](value, offset), "expected": value * args.target // 100}
                for value in cases if namespace["net"](value, offset) != value * args.target // 100]
    result.update(outcome="fail" if failures else "pass", failures=failures, cases=cases,
                  limits="Executed local integer component and configuration only; no physical or external-service measurement")
    print(json.dumps(result))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
