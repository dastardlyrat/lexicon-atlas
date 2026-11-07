"""Structural validation for the generated Lexicon Atlas artifacts."""

from __future__ import annotations

from hashlib import sha256
import gzip
import json
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "dist" / "data"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def shard(term: str) -> str:
    return sha256(term.encode("utf-8")).hexdigest()[:2]


def validate_shards(name: str, expected: int = 256, compressed: bool = False) -> None:
    directory = DATA / name
    pattern = "[0-9a-f][0-9a-f].json.gz" if compressed else "[0-9a-f][0-9a-f].json"
    paths = sorted(directory.glob(pattern))
    if len(paths) != expected:
        raise AssertionError(f"{name}: expected {expected} shards, found {len(paths)}")
    for path in paths:
        payload = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8")) if compressed else load(path)
        for term in payload:
            actual = path.name[:2]
            if shard(term) != actual:
                raise AssertionError(f"{name}: {term!r} is in shard {actual}")


def main() -> None:
    manifest = load(DATA / "manifest.json")
    if manifest["schema"] != "lexicon-atlas-data/4":
        raise AssertionError(f"unexpected schema: {manifest['schema']}")
    if manifest["counts"] != {"words": 135_969, "synsets": 107_519, "senses": 185_129}:
        raise AssertionError("OEWN release counts changed")
    terms = json.loads(gzip.decompress((DATA / "terms.json.gz").read_bytes()).decode("utf-8"))
    if terms != sorted(set(terms)):
        raise AssertionError("term index is not sorted and unique")
    if len(terms) != manifest["terms"]:
        raise AssertionError("term index count differs from manifest")
    validate_shards("words", compressed=True)
    validate_shards("lexical", compressed=True)
    validate_shards("gcide", compressed=True)
    if manifest["supplements"].get("wiktionary", {}).get("mode") == "complete local extraction":
        validate_shards("wiktionary", compressed=True)
        wiki = load(DATA / "wiktionary" / "manifest.json")
        accounted = (wiki["english_entries"] + wiki.get("skipped_non_english_rows", 0)
                     + wiki.get("skipped_empty_headwords", 0) + wiki.get("invalid_json_rows", 0))
        if wiki["input_rows"] != accounted or wiki["invalid_json_rows"] != 0 or wiki["shards"] != 256:
            raise AssertionError("Wiktionary import is incomplete")
    odict_dir = ROOT / "build-output" / "odict" / "gcide"
    if odict_dir.is_dir():
        for path in odict_dir.glob("*.odxml"):
            ET.parse(path)
    print(json.dumps({
        "schema": manifest["schema"],
        "terms": len(terms),
        "sources": sorted(manifest["supplements"]),
        "wiktionary_mode": manifest["supplements"]["wiktionary"]["mode"],
        "status": "structurally valid",
    }, indent=2))


if __name__ == "__main__":
    main()
