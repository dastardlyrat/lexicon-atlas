from __future__ import annotations

import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest

from finalize_data import FinalizationError, finalize_data


TERMS = ["florbin", "tavrel"]


def shard(term: str) -> str:
    return sha256(term.encode("utf-8")).hexdigest()[:2]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def fixture_records() -> tuple[dict, dict, dict, dict]:
    words = {
        "florbin": [
            {"id": "synthetic-florbin-n", "lemma": "florbin", "pos": "n", "senses": [
                {"id": "synthetic-florbin-tool", "synset": "synthetic-01-n", "relations": {
                    "contrast": [{"sense": "synthetic-florbin-bird", "lemma": "florbin", "synset": "synthetic-02-n"}],
                }},
                {"id": "synthetic-florbin-bird-entry", "synset": "synthetic-02-n", "relations": {}},
            ]},
        ],
        "tavrel": [
            {"id": "synthetic-tavrel-n", "lemma": "tavrel", "pos": "n", "senses": [
                {"id": "synthetic-tavrel-sense", "synset": "synthetic-03-n", "relations": {}},
            ]},
        ],
    }
    lexical = {
        "florbin": {"p": ["F L AO1 R B IH0 N"], "f": [["florbins", "N;PL"]]},
        "tavrel": {"l": ["tavrel"], "f": [["tavrels", "N;PL"]]},
    }
    synsets = {
        "synthetic-01-n": {
            "id": "synthetic-01-n", "pos": "n", "lemmas": ["florbin"],
            "definition": "an invented hand tool used only in this test fixture", "examples": [],
            "relations": {"associated": ["synthetic-03-n"]},
            "senses": [{"id": "synthetic-florbin-tool", "lemma": "florbin", "relations": {}}],
        },
        "synthetic-02-n": {
            "id": "synthetic-02-n", "pos": "n", "lemmas": ["florbin"],
            "definition": "an invented migratory bird used only in this test fixture", "examples": [],
            "relations": {},
            "senses": [{"id": "synthetic-florbin-bird", "lemma": "florbin", "relations": {}}],
        },
        "synthetic-03-n": {
            "id": "synthetic-03-n", "pos": "n", "lemmas": ["tavrel"],
            "definition": "an invented marker related to the synthetic tool", "examples": [],
            "relations": {},
            "senses": [{"id": "synthetic-tavrel-sense", "lemma": "tavrel", "relations": {}}],
        },
    }
    archive = {
        "florbin": [{"w": "florbin", "p": ["noun"], "d": ["a separate synthetic archive definition"], "x": [], "pr": []}],
        "tavrel": [{"w": "tavrel", "p": ["noun"], "d": ["a second synthetic archive record"], "x": [], "pr": []}],
    }
    return words, lexical, synsets, archive


def create_small_project(root: Path) -> Path:
    data = root / "dist" / "data"
    words, lexical, synsets, archive = fixture_records()
    word_groups: dict[str, dict] = {}
    lexical_groups: dict[str, dict] = {}
    archive_groups: dict[str, dict] = {}
    for term in TERMS:
        prefix = shard(term)
        word_groups.setdefault(prefix, {})[term] = words[term]
        lexical_groups.setdefault(prefix, {})[term] = lexical[term]
        archive_groups.setdefault(prefix, {})[term] = archive[term]
    write_json(data / "terms.json", TERMS)
    for prefix, values in word_groups.items():
        write_json(data / "words" / f"{prefix}.json", values)
    for prefix, values in lexical_groups.items():
        write_json(data / "lexical" / f"{prefix}.json", values)
    for prefix, values in archive_groups.items():
        write_json(data / "gcide" / f"{prefix}.json", values)
    write_json(data / "synsets" / "other.json", synsets)
    write_json(data / "manifest.json", {
        "schema": "lexicon-atlas-data/4",
        "fixture": {"kind": "synthetic", "license": "CC0-1.0", "usable_dictionary": False},
        "release": "synthetic-fixture/1",
        "label": "Synthetic lexical fixture",
        "language": "en-x-synthetic",
        "license": "CC0-1.0 test fixture",
        "counts": {"words": 2, "synsets": 3, "senses": 3},
        "terms": 2,
        "word_shards": len(word_groups),
        "lexical_shards": len(lexical_groups),
        "synset_shards": 1,
        "supplements": {
            "gcide": {"label": "Synthetic archive provider", "shards": len(archive_groups)},
            "wiktionary": {"label": "Synthetic absent provider", "mode": "absent"},
        },
    })
    return data


class FinalizerTests(unittest.TestCase):
    def test_repeat_finalization_is_byte_identical_and_inventoried(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            data = create_small_project(project)
            first = finalize_data(data, project_root=project, synthetic=True)
            first_bytes = {item["path"]: (data / item["path"]).read_bytes() for item in first["artifacts"]}
            second = finalize_data(data, project_root=project, synthetic=True)
            second_bytes = {item["path"]: (data / item["path"]).read_bytes() for item in second["artifacts"]}

            self.assertEqual(first, second)
            self.assertEqual(first_bytes, second_bytes)
            self.assertEqual(first["schema"], "lexicon-atlas-finalization/1")
            self.assertTrue(all(item["bytes"] > 0 for item in first["artifacts"]))
            self.assertTrue(all(len(item["sha256"]) == 64 for item in first["artifacts"]))
            terms = json.loads(gzip.decompress((data / "terms.json.gz").read_bytes()).decode("utf-8"))
            self.assertEqual(terms, TERMS)

    def test_invalid_json_fails_before_replacing_prior_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            data = create_small_project(project)
            inventory = finalize_data(data, project_root=project, synthetic=True)
            prior = {item["path"]: (data / item["path"]).read_bytes() for item in inventory["artifacts"]}
            source = next((data / "words").glob("*.json"))
            source.write_text("{truncated", encoding="utf-8")

            with self.assertRaisesRegex(FinalizationError, "Invalid JSON staging file"):
                finalize_data(data, project_root=project, synthetic=True)
            self.assertEqual(prior, {path: (data / path).read_bytes() for path in prior})

    def test_commit_error_rolls_back_every_prior_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            data = create_small_project(project)
            inventory = finalize_data(data, project_root=project, synthetic=True)
            tracked = [item["path"] for item in inventory["artifacts"]] + ["artifact-inventory.json"]
            prior = {path: (data / path).read_bytes() for path in tracked}
            write_json(data / "terms.json", list(reversed(TERMS)))
            calls = 0

            def fail_during_commit(source, target):
                nonlocal calls
                calls += 1
                if calls == 4:
                    raise OSError("injected replacement failure")
                os.replace(source, target)

            with self.assertRaisesRegex(FinalizationError, "rolled back"):
                finalize_data(data, project_root=project, synthetic=True, replace=fail_during_commit)
            self.assertEqual(prior, {path: (data / path).read_bytes() for path in tracked})

    def test_wrong_destination_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            data = create_small_project(project)
            outside = project / "data"
            outside.mkdir()
            with self.assertRaisesRegex(FinalizationError, "exact project dist/data"):
                finalize_data(outside, project_root=project, synthetic=True)
            self.assertFalse((outside / "artifact-inventory.json").exists())

    def test_stale_finalized_artifact_is_identified_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            data = create_small_project(project)
            expected_prefixes = {shard(term) for term in TERMS}
            stale_prefix = next(f"{index:02x}" for index in range(256) if f"{index:02x}" not in expected_prefixes)
            stale = data / "words" / f"{stale_prefix}.json.gz"
            stale.write_bytes(b"stale")
            with self.assertRaisesRegex(FinalizationError, "Stale finalized words artifacts"):
                finalize_data(data, project_root=project, synthetic=True)
            self.assertEqual(stale.read_bytes(), b"stale")
            self.assertFalse((data / "artifact-inventory.json").exists())

    def test_incomplete_production_hash_family_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            data = project / "dist" / "data"
            write_json(data / "terms.json", ["florbin"])
            write_json(data / "words" / f"{shard('florbin')}.json", {"florbin": []})
            write_json(data / "manifest.json", {
                "schema": "lexicon-atlas-data/4", "word_shards": 256,
                "lexical_shards": 256, "synset_shards": 1, "supplements": {},
            })
            with self.assertRaisesRegex(FinalizationError, "declares 256 shards, found 1"):
                finalize_data(data, project_root=project)


if __name__ == "__main__":
    unittest.main()
