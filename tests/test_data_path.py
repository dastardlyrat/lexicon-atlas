from __future__ import annotations

import functools
import gzip
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import urlopen

from finalize_data import finalize_data
from validate_build import validate_build


TERMS = ["florbin", "tavrel"]


def shard(term: str) -> str:
    return sha256(term.encode("utf-8")).hexdigest()[:2]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def create_complete_fixture(project: Path) -> Path:
    data = project / "dist" / "data"
    word_values = {
        "florbin": [{"id": "synthetic-florbin", "lemma": "florbin", "pos": "n", "senses": [
            {"id": "synthetic-florbin-tool", "synset": "synthetic-01-n", "relations": {
                "contrast": [{"sense": "synthetic-florbin-bird", "lemma": "florbin", "synset": "synthetic-02-n"}],
            }},
            {"id": "synthetic-florbin-bird", "synset": "synthetic-02-n", "relations": {}},
        ]}],
        "tavrel": [{"id": "synthetic-tavrel", "lemma": "tavrel", "pos": "n", "senses": [
            {"id": "synthetic-tavrel-sense", "synset": "synthetic-03-n", "relations": {}},
        ]}],
    }
    lexical_values = {
        "florbin": {"p": ["F L AO1 R B IH0 N"], "f": [["florbins", "N;PL"]]},
        "tavrel": {"l": ["tavrel"], "f": [["tavrels", "N;PL"]]},
    }
    archive_values = {
        "florbin": [{"w": "florbin", "p": ["noun"], "d": ["a separate synthetic archive definition"], "x": [], "pr": []}],
        "tavrel": [{"w": "tavrel", "p": ["noun"], "d": ["another separate synthetic record"], "x": [], "pr": []}],
    }
    by_family = {"words": word_values, "lexical": lexical_values, "gcide": archive_values}
    for family, records in by_family.items():
        for index in range(256):
            prefix = f"{index:02x}"
            payload = {term: records[term] for term in TERMS if shard(term) == prefix}
            write_json(data / family / f"{prefix}.json", payload)
    write_json(data / "terms.json", TERMS)
    write_json(data / "synsets" / "other.json", {
        "synthetic-01-n": {"id": "synthetic-01-n", "pos": "n", "lemmas": ["florbin"],
            "definition": "an invented hand tool", "examples": [],
            "relations": {"associated": ["synthetic-03-n"]},
            "senses": [{"id": "synthetic-florbin-tool", "lemma": "florbin", "relations": {}}]},
        "synthetic-02-n": {"id": "synthetic-02-n", "pos": "n", "lemmas": ["florbin"],
            "definition": "an invented migratory bird", "examples": [], "relations": {},
            "senses": [{"id": "synthetic-florbin-bird", "lemma": "florbin", "relations": {}}]},
        "synthetic-03-n": {"id": "synthetic-03-n", "pos": "n", "lemmas": ["tavrel"],
            "definition": "an invented related marker", "examples": [], "relations": {},
            "senses": [{"id": "synthetic-tavrel-sense", "lemma": "tavrel", "relations": {}}]},
    })
    write_json(data / "manifest.json", {
        "schema": "lexicon-atlas-data/4", "release": "synthetic-fixture/1",
        "fixture": {"kind": "synthetic", "license": "CC0-1.0", "usable_dictionary": False},
        "label": "Synthetic lexical fixture", "language": "en-x-synthetic",
        "license": "CC0-1.0 test fixture",
        "counts": {"words": 2, "synsets": 3, "senses": 3}, "terms": 2,
        "word_shards": 256, "lexical_shards": 256, "synset_shards": 1,
        "supplements": {
            "gcide": {"label": "Synthetic archive provider", "shards": 256},
            "wiktionary": {"label": "Synthetic absent provider", "mode": "absent"},
        },
    })
    return data


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class DataPathTests(unittest.TestCase):
    def test_finalized_fixture_validates_and_serves_browser_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            data = create_complete_fixture(project)
            inventory = finalize_data(data, project_root=project, synthetic=True)
            report = validate_build(data, "synthetic")
            self.assertEqual(report["status"], "structurally valid")
            self.assertEqual(len(inventory["artifacts"]), 770)

            handler = functools.partial(QuietHandler, directory=str(project / "dist"))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}/data"

            def get_gzip_json(relative: str):
                with urlopen(f"{base}/{relative}", timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    return json.loads(gzip.decompress(response.read()).decode("utf-8"))

            try:
                self.assertEqual(get_gzip_json("terms.json.gz"), TERMS)
                words = get_gzip_json(f"words/{shard('florbin')}.json.gz")
                lexical = get_gzip_json(f"lexical/{shard('florbin')}.json.gz")
                archive = get_gzip_json(f"gcide/{shard('florbin')}.json.gz")
                synsets = get_gzip_json("synsets/other.json.gz")
                self.assertEqual(len(words["florbin"][0]["senses"]), 2)
                self.assertIn("p", lexical["florbin"])
                self.assertIn("florbin", archive)
                selected = words["florbin"][0]["senses"][0]
                self.assertIn(selected["synset"], synsets)
                relation_target = synsets[selected["synset"]]["relations"]["associated"][0]
                self.assertIn(relation_target, synsets)
                absent = "unlisted-synthetic-word"
                self.assertNotIn(absent, get_gzip_json(f"words/{shard(absent)}.json.gz"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            (data / "terms.json.gz").write_bytes(b"truncated-gzip")
            with self.assertRaisesRegex(AssertionError, "invalid gzip JSON"):
                validate_build(data, "synthetic")


if __name__ == "__main__":
    unittest.main()
