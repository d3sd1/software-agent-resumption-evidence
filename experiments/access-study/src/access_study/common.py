"""Trusted host utilities; public source is read as data, never imported here."""
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=True, sort_keys=True)
        stream.write("\n")


def stamp():
    return datetime.now(timezone.utc).isoformat()


def append(path, value):
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(canonical(value).decode() + "\n")
        stream.flush()


def settings():
    return read(ROOT / "config.json")


def safe_child(root, name):
    root = Path(root).resolve()
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Unsafe relative path")
    path = root / relative
    if any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
        raise ValueError("Symlink refused")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Path escaped root")
    return path


def inventory(root):
    root = Path(root)
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlink in manifest")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha(path.read_bytes())
    return result


def subject(full):
    return {name: digest for name, digest in full.items() if name.startswith("source/")}


def verify_tree(root, expected):
    if inventory(root) != expected:
        raise RuntimeError("File set or hash mismatch: " + str(root))


def copy_verified(src, dest, manifest):
    verify_tree(src, manifest)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=False)
    for name, digest in manifest.items():
        data = safe_child(src, name).read_bytes()
        if sha(data) != digest:
            raise RuntimeError("Source changed during copy")
        target = safe_child(dest, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    verify_tree(dest, manifest)


def source_hashes():
    paths = [ROOT / name for name in ("study.py", "config.json", "api-contract.json", "README.md",
                                      "requirements.txt", ".gitignore", "protocol-v1.md", "protocol-review-1.md")]
    paths += sorted((ROOT / "src/access_study").glob("*.py"))
    paths += sorted((ROOT / "tests").rglob("*.py"))
    paths += sorted((ROOT / "tools").rglob("*.py"))
    return {p.relative_to(ROOT).as_posix(): sha(p.read_bytes()) for p in paths}
