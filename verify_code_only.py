"""Fail when external lexical data or generated dictionary artifacts enter Git."""

from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent
FORBIDDEN_PARTS = {".lexical_sources", "vendor", "build-output", ".wn_data", "node_modules"}
FORBIDDEN_SUFFIXES = {
    ".db", ".sqlite", ".sqlite3", ".dict", ".idx", ".ifo", ".odict",
    ".odxml", ".jsonl", ".gz", ".tar", ".xz", ".zip",
}
ALLOWED_DATA_FILES = {Path("dist/data/.gitkeep"), Path("dist/data/README.md")}
MAX_FILE_BYTES = 2 * 1024 * 1024


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT}", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [Path(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item]


def main() -> int:
    violations: list[str] = []
    for relative in tracked_files():
        path = ROOT / relative
        if FORBIDDEN_PARTS.intersection(relative.parts):
            violations.append(f"forbidden directory: {relative}")
        if relative.parts[:2] == ("dist", "data") and relative not in ALLOWED_DATA_FILES:
            violations.append(f"generated data path: {relative}")
        if path.suffix.casefold() in FORBIDDEN_SUFFIXES:
            violations.append(f"dictionary/archive extension: {relative}")
        if path.is_file() and path.stat().st_size > MAX_FILE_BYTES:
            violations.append(f"file exceeds {MAX_FILE_BYTES} bytes: {relative}")
    if violations:
        print("Code-only verification failed:")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print(f"Code-only verification passed: {len(tracked_files())} tracked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
