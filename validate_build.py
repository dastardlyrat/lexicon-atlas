"""Structural validation for finalized Lexicon Atlas browser artifacts."""

from __future__ import annotations

import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "dist" / "data"
PRODUCTION_COUNTS = {"words": 135_969, "synsets": 107_519, "senses": 185_129}


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AssertionError(f"invalid JSON {path}: {error}") from error


def load_gzip(path: Path):
    try:
        return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AssertionError(f"invalid gzip JSON {path}: {error}") from error


def shard(term: str) -> str:
    return sha256(term.encode("utf-8")).hexdigest()[:2]


def validate_shards(
        data_root: Path,
        name: str,
        expected: int,
        *,
        hashed_terms: bool = True,
        ) -> list[Path]:
    directory = data_root / name
    pattern = "[0-9a-f][0-9a-f].json.gz" if hashed_terms else "*.json.gz"
    paths = sorted(directory.glob(pattern))
    if len(paths) != expected:
        raise AssertionError(f"{name}: expected {expected} shards, found {len(paths)}")
    for path in paths:
        payload = load_gzip(path)
        if not isinstance(payload, dict):
            raise AssertionError(f"{path}: shard payload must be an object")
        if hashed_terms:
            for term in payload:
                actual = path.name[:2]
                if shard(term) != actual:
                    raise AssertionError(f"{name}: {term!r} is in shard {actual}")
    return paths


def validate_build(data_root: Path = DATA, profile: str = "production") -> dict:
    data_root = Path(data_root).resolve()
    manifest = load(data_root / "manifest.json")
    if manifest.get("schema") != "lexicon-atlas-data/4":
        raise AssertionError(f"unexpected schema: {manifest.get('schema')}")
    if profile == "production" and manifest.get("counts") != PRODUCTION_COUNTS:
        raise AssertionError("OEWN release counts changed")
    if profile not in {"production", "synthetic"}:
        raise AssertionError(f"unknown validation profile: {profile}")
    fixture = manifest.get("fixture")
    if profile == "synthetic":
        if (not isinstance(fixture, dict) or fixture.get("kind") != "synthetic"
                or not fixture.get("license")):
            raise AssertionError("synthetic profile requires an explicitly licensed fixture manifest")
    elif fixture is not None:
        raise AssertionError("synthetic fixture cannot use the production validation profile")

    terms = load_gzip(data_root / "terms.json.gz")
    if not isinstance(terms, list) or terms != sorted(set(terms)):
        raise AssertionError("term index is not sorted and unique")
    if len(terms) != manifest.get("terms"):
        raise AssertionError("term index count differs from manifest")

    word_shards = manifest.get("word_shards")
    lexical_shards = manifest.get("lexical_shards")
    synset_shards = manifest.get("synset_shards")
    for label, value in (("word_shards", word_shards), ("lexical_shards", lexical_shards),
                         ("synset_shards", synset_shards)):
        if not isinstance(value, int) or value < 1:
            raise AssertionError(f"invalid manifest field: {label}")
    if profile == "production" and (word_shards != 256 or lexical_shards != 256):
        raise AssertionError("production word and lexical families must each contain 256 shards")

    validate_shards(data_root, "words", word_shards)
    validate_shards(data_root, "lexical", lexical_shards)
    validate_shards(data_root, "synsets", synset_shards, hashed_terms=False)

    supplements = manifest.get("supplements") or {}
    if not isinstance(supplements, dict):
        raise AssertionError("manifest supplements must be an object")
    gcide = supplements.get("gcide")
    if gcide is not None:
        gcide_shards = gcide.get("shards") if isinstance(gcide, dict) else None
        if not isinstance(gcide_shards, int) or gcide_shards < 1:
            raise AssertionError("GCIDE supplement does not declare a valid shard count")
        if profile == "production" and gcide_shards != 256:
            raise AssertionError("production GCIDE family must contain 256 shards")
        validate_shards(data_root, "gcide", gcide_shards)

    wiktionary = supplements.get("wiktionary") or {}
    wiktionary_mode = wiktionary.get("mode", "absent") if isinstance(wiktionary, dict) else "invalid"
    if wiktionary_mode == "complete local extraction":
        wiki_shards = wiktionary.get("shards")
        if not isinstance(wiki_shards, int) or wiki_shards < 1:
            raise AssertionError("Wiktionary supplement does not declare a valid shard count")
        if profile == "production" and wiki_shards != 256:
            raise AssertionError("production Wiktionary family must contain 256 shards")
        validate_shards(data_root, "wiktionary", wiki_shards)
        wiki = load(data_root / "wiktionary" / "manifest.json")
        accounted = (wiki["english_entries"] + wiki.get("skipped_non_english_rows", 0)
                     + wiki.get("skipped_empty_headwords", 0) + wiki.get("invalid_json_rows", 0))
        if (wiki["input_rows"] != accounted or wiki["invalid_json_rows"] != 0
                or wiki["shards"] != wiki_shards):
            raise AssertionError("Wiktionary import is incomplete")

    odict_dir = ROOT / "build-output" / "odict" / "gcide"
    if data_root == DATA.resolve() and odict_dir.is_dir():
        for path in odict_dir.glob("*.odxml"):
            ET.parse(path)

    return {
        "schema": manifest["schema"],
        "profile": profile,
        "terms": len(terms),
        "sources": sorted(supplements),
        "wiktionary_mode": wiktionary_mode,
        "status": "structurally valid",
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--data-root", type=Path, default=DATA)
    result.add_argument("--profile", choices=("production", "synthetic"), default="production")
    return result


def main() -> None:
    args = parser().parse_args()
    print(json.dumps(validate_build(args.data_root, args.profile), indent=2))


if __name__ == "__main__":
    main()
