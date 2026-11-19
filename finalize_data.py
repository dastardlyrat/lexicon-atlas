"""Finalize staged Lexicon Atlas JSON into deterministic browser assets.

This module does not acquire or interpret lexical sources.  It validates the
declared staging tree, serializes each JSON value deterministically, and
atomically replaces only the corresponding ``.json.gz`` browser artifact.
"""

from __future__ import annotations

import argparse
import gzip
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Callable


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "dist" / "data"
INVENTORY_NAME = "artifact-inventory.json"
INVENTORY_SCHEMA = "lexicon-atlas-finalization/1"
HASH_SHARD_RE = re.compile(r"[0-9a-f]{2}\.json")
SYNSET_SHARD_RE = re.compile(r"(?:[0-9]{2}|other)\.json")


class FinalizationError(RuntimeError):
    """Raised when the staging tree cannot be finalized safely."""


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FinalizationError(f"Invalid JSON staging file {path.name}: {error}") from error


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _deterministic_gzip(value: object) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, compresslevel=9, mtime=0) as archive:
        archive.write(_canonical_json(value))
    return output.getvalue()


def _write_fsynced(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _declared_count(manifest: dict, key: str) -> int:
    value = manifest.get(key)
    if not isinstance(value, int) or value < 1:
        raise FinalizationError(f"Manifest field {key!r} must be a positive integer")
    return value


def _family_sources(
        data_root: Path,
        family: str,
        expected: int,
        name_pattern: re.Pattern[str],
        require_complete_hash_family: bool) -> list[Path]:
    directory = data_root / family
    if not directory.is_dir():
        raise FinalizationError(f"Missing staged family directory: {family}")
    sources = sorted(path for path in directory.glob("*.json") if path.name != "manifest.json")
    unexpected = [path.name for path in sources if not name_pattern.fullmatch(path.name)]
    if unexpected:
        raise FinalizationError(f"Unexpected {family} staging names: {', '.join(unexpected[:5])}")
    if len(sources) != expected:
        raise FinalizationError(f"{family}: manifest declares {expected} shards, found {len(sources)}")
    if require_complete_hash_family and expected != 256:
        raise FinalizationError(f"{family}: production hash family must contain 256 shards, found {expected}")
    return sources


def _validate_existing_gzip(path: Path) -> object:
    try:
        return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FinalizationError(f"Invalid existing gzip JSON {path.name}: {error}") from error


def _artifact_record(data_root: Path, path: Path, payload: bytes, mode: str) -> dict:
    return {
        "path": path.relative_to(data_root).as_posix(),
        "bytes": len(payload),
        "sha256": sha256(payload).hexdigest(),
        "mode": mode,
    }


def finalize_data(
        data_root: Path = DATA,
        *,
        project_root: Path = ROOT,
        synthetic: bool = False,
        replace: Callable[[str | os.PathLike[str], str | os.PathLike[str]], None] = os.replace,
        ) -> dict:
    """Finalize one verified data tree and return its deterministic inventory.

    ``project_root`` exists so tests can construct an isolated project-shaped
    directory.  In every invocation the target must resolve to that project's
    exact ``dist/data`` directory.
    """

    project_root = Path(project_root).resolve()
    data_root = Path(data_root).resolve()
    expected_root = (project_root / "dist" / "data").resolve()
    if data_root != expected_root:
        raise FinalizationError(f"Refusing target outside the exact project dist/data directory: {data_root}")
    if not data_root.is_dir():
        raise FinalizationError(f"Data directory does not exist: {data_root}")

    manifest_path = data_root / "manifest.json"
    manifest_value = _load_json(manifest_path)
    if not isinstance(manifest_value, dict):
        raise FinalizationError("manifest.json must contain an object")
    manifest = manifest_value
    if manifest.get("schema") != "lexicon-atlas-data/4":
        raise FinalizationError(f"Unsupported data schema: {manifest.get('schema')!r}")
    fixture = manifest.get("fixture")
    if synthetic:
        if (not isinstance(fixture, dict) or fixture.get("kind") != "synthetic"
                or not fixture.get("license")):
            raise FinalizationError("Synthetic mode requires an explicitly licensed synthetic fixture manifest")
    elif fixture is not None:
        raise FinalizationError("A synthetic fixture cannot be finalized with the production profile")

    terms_path = data_root / "terms.json"
    if not terms_path.is_file():
        raise FinalizationError("Missing staged term index: terms.json")

    families: list[tuple[str, list[Path]]] = [
        ("words", _family_sources(
            data_root, "words", _declared_count(manifest, "word_shards"), HASH_SHARD_RE, not synthetic)),
        ("lexical", _family_sources(
            data_root, "lexical", _declared_count(manifest, "lexical_shards"), HASH_SHARD_RE, not synthetic)),
        ("synsets", _family_sources(
            data_root, "synsets", _declared_count(manifest, "synset_shards"), SYNSET_SHARD_RE, False)),
    ]

    supplements = manifest.get("supplements") or {}
    if not isinstance(supplements, dict):
        raise FinalizationError("Manifest supplements must be an object")
    gcide = supplements.get("gcide")
    if gcide is not None:
        if not isinstance(gcide, dict) or not isinstance(gcide.get("shards"), int):
            raise FinalizationError("GCIDE supplement must declare its shard count")
        families.append(("gcide", _family_sources(
            data_root, "gcide", gcide["shards"], HASH_SHARD_RE, not synthetic)))
    elif (data_root / "gcide").is_dir() and any((data_root / "gcide").glob("*.json*")):
        raise FinalizationError("GCIDE files exist but the supplement is not declared in manifest.json")

    staging_sources = [(terms_path, data_root / "terms.json.gz")]
    for _, sources in families:
        staging_sources.extend((source, source.with_suffix(source.suffix + ".gz")) for source in sources)

    expected_targets = {target.resolve() for _, target in staging_sources}
    for family, _ in families:
        extras = sorted(
            path.relative_to(data_root).as_posix()
            for path in (data_root / family).glob("*.json.gz")
            if path.resolve() not in expected_targets
        )
        if extras:
            raise FinalizationError(f"Stale finalized {family} artifacts: {', '.join(extras[:5])}")

    # Parse every staging value before the first finalized byte is prepared.
    parsed = [(source, target, _load_json(source)) for source, target in staging_sources]

    preserved: list[tuple[Path, bytes]] = []
    wiktionary = supplements.get("wiktionary") or {}
    if isinstance(wiktionary, dict) and wiktionary.get("mode") == "complete local extraction":
        expected_wiki = wiktionary.get("shards")
        if not isinstance(expected_wiki, int) or expected_wiki < 1:
            raise FinalizationError("Local Wiktionary supplement must declare its shard count")
        wiki_paths = sorted((data_root / "wiktionary").glob("[0-9a-f][0-9a-f].json.gz"))
        if len(wiki_paths) != expected_wiki or (not synthetic and expected_wiki != 256):
            raise FinalizationError(
                f"wiktionary: manifest declares {expected_wiki} shards, found {len(wiki_paths)}")
        for path in wiki_paths:
            _validate_existing_gzip(path)
            preserved.append((path, path.read_bytes()))

    staging_root = Path(tempfile.mkdtemp(prefix=".finalize-", dir=data_root))
    backup_root = staging_root / "backups"
    staged_outputs: list[tuple[Path, Path]] = []
    artifact_records: list[dict] = []
    try:
        for source, target, value in parsed:
            payload = _deterministic_gzip(value)
            stage = staging_root / "outputs" / target.relative_to(data_root)
            _write_fsynced(stage, payload)
            staged_outputs.append((stage, target))
            artifact_records.append(_artifact_record(data_root, target, payload, "generated"))

        for path, payload in preserved:
            artifact_records.append(_artifact_record(data_root, path, payload, "preserved"))

        artifact_records.sort(key=lambda item: item["path"])
        inventory = {
            "schema": INVENTORY_SCHEMA,
            "data_schema": manifest["schema"],
            "profile": "synthetic" if synthetic else "production",
            "serialization": {
                "encoding": "utf-8",
                "json_separators": [",", ":"],
                "sort_keys": True,
                "gzip_compresslevel": 9,
                "gzip_mtime": 0,
            },
            "artifacts": artifact_records,
        }
        inventory_target = data_root / INVENTORY_NAME
        inventory_stage = staging_root / "outputs" / INVENTORY_NAME
        _write_fsynced(inventory_stage, _canonical_json(inventory))
        staged_outputs.append((inventory_stage, inventory_target))

        transactions: list[tuple[Path, Path, bool]] = []
        try:
            for index, (stage, target) in enumerate(staged_outputs):
                backup = backup_root / f"{index:05d}.bak"
                had_prior = target.is_file()
                if had_prior:
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    replace(target, backup)
                transactions.append((target, backup, had_prior))
                replace(stage, target)
        except Exception as error:
            rollback_errors = []
            for target, backup, had_prior in reversed(transactions):
                try:
                    if target.exists():
                        target.unlink()
                    if had_prior and backup.exists():
                        replace(backup, target)
                except Exception as rollback_error:  # pragma: no cover - catastrophic filesystem failure
                    rollback_errors.append(str(rollback_error))
            detail = f"; rollback errors: {'; '.join(rollback_errors)}" if rollback_errors else ""
            raise FinalizationError(f"Finalization commit failed and was rolled back: {error}{detail}") from error

        return inventory
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--data-root", type=Path, default=DATA,
                        help="must resolve to this checkout's exact dist/data directory")
    result.add_argument("--synthetic", action="store_true",
                        help="allow reduced shard counts for an explicitly synthetic fixture")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        inventory = finalize_data(args.data_root, synthetic=args.synthetic)
    except FinalizationError as error:
        print(f"Finalization failed: {error}")
        return 1
    inventory_bytes = _canonical_json(inventory)
    print(json.dumps({
        "schema": inventory["schema"],
        "profile": inventory["profile"],
        "artifacts": len(inventory["artifacts"]),
        "inventory_sha256": sha256(inventory_bytes).hexdigest(),
        "status": "finalized",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
