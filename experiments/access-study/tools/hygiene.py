"""Own-source deterministic hygiene over loopback only. No detector or rewrite."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import urllib.request
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--service", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    url = urllib.parse.urlparse(args.service)
    if url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Only local loopback service allowed")
    output = Path(args.output).resolve()
    if not output.is_relative_to(ROOT / "local-validation") or output.exists():
        raise ValueError("Use a new local-validation receipt")
    with urllib.request.urlopen(args.service + "/health", timeout=10) as response:
        health = json.load(response)
    own = [ROOT / "study.py", ROOT / "config.json", ROOT / "api-contract.json", ROOT / "README.md",
           ROOT / "requirements.txt", ROOT / ".gitignore"]
    own += sorted((ROOT / "src/access_study").glob("*.py"))
    own += sorted((ROOT / "tests").glob("*.py"))
    own += sorted((ROOT / "tools").glob("*.py"))
    rows = []
    for path in own:
        original = path.read_bytes()
        body = {"file": base64.b64encode(original).decode(), "name": path.name + ".txt",
                "options": {"nfkc": False, "aggressive_homoglyphs": False,
                            "detect_before": False, "detect_after": False}}
        responses = {}
        for operation in ("inspect", "clean"):
            request = urllib.request.Request(args.service + "/" + operation,
                                             data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=30) as response:
                responses[operation] = json.load(response)
        if not responses["clean"].get("ok"):
            raise RuntimeError("Local cleaner failed: " + path.name)
        cleaned = base64.b64decode(responses["clean"]["cleaned"])
        if cleaned != original:
            path.write_bytes(cleaned)
        rows.append({"path": str(path.relative_to(ROOT)), "changed": cleaned != original,
                     "before_sha256": hashlib.sha256(original).hexdigest(),
                     "after_sha256": hashlib.sha256(cleaned).hexdigest(),
                     "inspect": responses["inspect"], "clean_report": responses["clean"].get("report")})
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump({"health": health, "scope": "own source only; loopback; no detection/rewrite/publication",
                   "files": rows}, stream, indent=2)
    print(json.dumps({"own_files": len(rows), "changed": sum(r["changed"] for r in rows),
                      "external_requests": 0}))


if __name__ == "__main__":
    main()
