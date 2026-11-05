#!/usr/bin/env python3
"""Local-only defaults. Run with python3 -I; no third-party imports or SDK."""
import argparse
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE / "src"))  # Own trusted implementation, never downloads.
from access_study.common import ROOT, write, source_hashes, stamp


def scoped_output(value):
    path = Path(value).resolve()
    if not path.is_relative_to(ROOT) or path == ROOT:
        raise ValueError("All output must stay under access-study")
    rel = path.relative_to(ROOT)
    if rel.parts[0] == "curation" or rel.parts[0].startswith("protocol"):
        raise ValueError("Curation and protocols are read-only")
    return path


def unit_tests(output):
    import unittest
    import io
    stream = io.StringIO()
    start = time.monotonic()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    text = stream.getvalue()
    print(text, end="")
    receipt = {"kind": "synthetic_unit_tests_not_public_cases", "passed": result.wasSuccessful(),
               "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
               "skipped": len(result.skipped), "log": text, "model_calls": 0,
               "wall_seconds": time.monotonic() - start, "source_hashes": source_hashes(), "at": stamp()}
    write(output, receipt)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--output", required=True)
    p = sub.add_parser("test")
    p.add_argument("--output", required=True)
    p = sub.add_parser("validate")
    p.add_argument("--prepared", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("freeze")
    for name in ("prepared", "validation", "tests", "preflight", "review", "output"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--freeze", action="store_true", help="Explicit coordinator step; does not authorize participants")
    p = sub.add_parser("verify-freeze")
    p.add_argument("--frozen", required=True)
    p = sub.add_parser("run")
    p.add_argument("--frozen", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--authorization", required=True)
    p.add_argument("--run", action="store_true", help="Necessary explicit flag, not evidence of consent")
    p = sub.add_parser("evaluate")
    p.add_argument("--run-folder", required=True)
    args = parser.parse_args()
    if args.operation == "test":
        unit_tests(scoped_output(args.output))
    elif args.operation == "prepare":
        from access_study.prepare import prepare
        result = prepare(scoped_output(args.output))
        print({"prepared": True, "model_calls": 0, "shared_seconds": result["shared_seconds"]})
    elif args.operation == "validate":
        from access_study.policies import validate
        result = validate(Path(args.prepared), scoped_output(args.output))
        print({k: v for k, v in result.items() if k not in ("controls", "artifact_hashes", "source_hashes")})
    elif args.operation == "freeze":
        if not args.freeze:
            parser.error("Freeze not requested; use --freeze only after coordinator review/preflight")
        from access_study.freeze import build
        build(Path(args.prepared), Path(args.validation), Path(args.tests), Path(args.preflight),
              Path(args.review), scoped_output(args.output))
        print("Freeze created. No participant launched.")
    elif args.operation == "verify-freeze":
        from access_study.freeze import verify
        print({"verified": bool(verify(Path(args.frozen))), "model_calls": 0})
    elif args.operation == "run":
        if not args.run:
            parser.error("Participant calls blocked: --run absent; no model invoked")
        from access_study.run_all import run
        run(Path(args.frozen), scoped_output(args.output), Path(args.authorization))
    else:
        from access_study.evaluate import evaluate_run
        evaluate_run(scoped_output(args.run_folder))


if __name__ == "__main__":
    main()
