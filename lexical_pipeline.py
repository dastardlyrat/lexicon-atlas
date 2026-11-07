"""Reproducible offline adapters for Wiktionary, GCIDE, StarDict, and ODict.

Raw source files live under .lexical_sources/ and derived working data under
build-output/.  Neither directory is versioned.  Browser-ready shards are
written to dist/data and keep every provider visibly separate.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import ExitStack
import gzip
from hashlib import sha256
import html
import json
import os
from pathlib import Path
import re
import shutil
import struct
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent
SOURCES = Path(os.environ["LEXICON_DATA_ROOT"]).expanduser() if os.environ.get("LEXICON_DATA_ROOT") else ROOT / ".lexical_sources"
BUILD = ROOT / "build-output"
DATA = ROOT / "dist" / "data"
WIKTIONARY_SOURCE_URL = "https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl"
WIKTIONARY_FILE = SOURCES / "wiktionary" / "kaikki.org-dictionary-English.jsonl"
GCIDE_DIR = SOURCES / "gcide" / "gcide-0.54"
GCIDE_ARCHIVE = SOURCES / "gcide" / "gcide-0.54.tar.xz"
ODICT_REVISION = "6a2bb5ab7a3d33b185ce6341381525b91c75e990"
GCIDE_VERSION = "0.54"
PIPELINE_SCHEMA = "lexicon-atlas-import/1"


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def shard_for(term: str) -> str:
    return sha256(term.encode("utf-8")).hexdigest()[:2]


def file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def write_gzip_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    temporary.write_bytes(gzip.compress(encoded, compresslevel=9, mtime=0))
    temporary.replace(path)


def merge_terms(new_terms: set[str]) -> int:
    path = DATA / "terms.json"
    existing = set(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else set()
    existing.update(new_terms)
    write_json(path, sorted(existing))
    manifest_path = DATA / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["terms"] = len(existing)
        write_json(manifest_path, manifest)
    return len(existing)


def attach_supplement(key: str, record: dict) -> None:
    path = DATA / "manifest.json"
    if not path.is_file():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.setdefault("supplements", {})[key] = record
    write_json(path, manifest)


def compact_wiktionary(row: dict) -> dict:
    pronunciations = []
    for sound in row.get("sounds") or []:
        compact = {k: sound[k] for k in ("ipa", "enpr", "tags", "audio", "ogg_url", "mp3_url") if sound.get(k)}
        if compact:
            pronunciations.append(compact)
    forms = []
    for form in row.get("forms") or []:
        if form.get("form"):
            forms.append({k: form[k] for k in ("form", "tags", "source") if form.get(k)})
    senses = []
    for sense in row.get("senses") or []:
        item = {k: sense[k] for k in ("id", "glosses", "tags", "synonyms", "antonyms", "hypernyms", "hyponyms", "derived") if sense.get(k)}
        examples = []
        for example in sense.get("examples") or []:
            if example.get("text"):
                examples.append({k: example[k] for k in ("text", "english") if example.get(k)})
        if examples:
            item["examples"] = examples
        if item:
            senses.append(item)
    return {
        "w": row.get("word", ""),
        "p": row.get("pos") or "",
        "e": row.get("etymology_text") or "",
        "pr": pronunciations,
        "f": forms,
        "s": senses,
    }


def finalize_jsonl_shards(source_dir: Path, output_dir: Path) -> tuple[int, int]:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    entry_count = 0
    nonempty = 0
    for shard_path in sorted(source_dir.glob("*.jsonl")):
        groups: dict[str, list[dict]] = defaultdict(list)
        with shard_path.open(encoding="utf-8") as source:
            for line in source:
                record = json.loads(line)
                groups[record.pop("_key")].append(record)
                entry_count += 1
        write_gzip_json(output_dir / f"{shard_path.stem}.json.gz", dict(groups))
        nonempty += 1
    return entry_count, nonempty


def import_wiktionary(_: argparse.Namespace) -> None:
    if not WIKTIONARY_FILE.is_file():
        raise FileNotFoundError(f"Place an obtained Kaikki English JSONL file at: {WIKTIONARY_FILE}")
    working = BUILD / "wiktionary-jsonl"
    if working.exists():
        shutil.rmtree(working)
    working.mkdir(parents=True)
    terms: set[str] = set()
    lines = english_rows = invalid = skipped_non_english = skipped_empty = 0
    with ExitStack() as stack:
        writers = {f"{index:02x}": stack.enter_context((working / f"{index:02x}.jsonl").open("w", encoding="utf-8"))
                   for index in range(256)}
        with WIKTIONARY_FILE.open(encoding="utf-8") as source:
            for line in source:
                lines += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    invalid += 1
                    continue
                if row.get("lang_code") != "en":
                    skipped_non_english += 1
                    continue
                term = normalize(row.get("word") or "")
                if not term:
                    skipped_empty += 1
                    continue
                compact = compact_wiktionary(row)
                compact["_key"] = term
                writers[shard_for(term)].write(json.dumps(compact, ensure_ascii=False, separators=(",", ":")) + "\n")
                terms.add(term)
                english_rows += 1
                if lines % 100_000 == 0:
                    print(f"read {lines:,} rows; kept {english_rows:,}; terms {len(terms):,}", flush=True)
    if invalid:
        raise RuntimeError(f"Wiktionary input contained {invalid} invalid JSON lines; working shards preserved")
    count, shards = finalize_jsonl_shards(working, DATA / "wiktionary")
    inventory = {
        "schema": PIPELINE_SCHEMA,
        "label": "English Wiktionary via Kaikki",
        "authority": "supplemental lexical evidence",
        "scope": "local English entries, senses, etymologies, forms, and pronunciations",
        "mode": "complete local extraction",
        "source_url": WIKTIONARY_SOURCE_URL,
        "license": "CC BY-SA 3.0 and GFDL",
        "wiktionary_dump_date": "2026-09-02",
        "extraction_date": "2026-09-25",
        "source_bytes": WIKTIONARY_FILE.stat().st_size,
        "source_sha256": file_hash(WIKTIONARY_FILE),
        "input_rows": lines,
        "english_entries": english_rows,
        "skipped_non_english_rows": skipped_non_english,
        "skipped_empty_headwords": skipped_empty,
        "invalid_json_rows": invalid,
        "terms": len(terms),
        "shards": shards,
    }
    write_json(DATA / "wiktionary" / "manifest.json", inventory)
    total_terms = merge_terms(terms)
    inventory["atlas_terms_after_merge"] = total_terms
    attach_supplement("wiktionary", inventory)
    write_json(BUILD / "wiktionary-import.json", inventory)
    print(json.dumps(inventory, indent=2))


TAG_RE = re.compile(r"<[^>]+>")
ENTRY_RE = re.compile(r"(?s)<p><ent>(.*?)</p>")


def clean_gcide(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = TAG_RE.sub("", value)
    return " ".join(html.unescape(value).split())


def import_gcide(_: argparse.Namespace) -> None:
    files = sorted(GCIDE_DIR.glob("CIDE.*"))
    if len(files) != 26:
        raise FileNotFoundError(f"Expected 26 GCIDE letter files under {GCIDE_DIR}")
    records: dict[str, list[dict]] = defaultdict(list)
    source_entries = 0
    for path in files:
        text = path.read_text(encoding="latin-1", errors="replace")
        for block in ENTRY_RE.findall(text):
            source_entries += 1
            ent_match = re.search(r"(?s)^(.*?)</ent>", block)
            if not ent_match:
                continue
            display = clean_gcide(ent_match.group(1))
            term = normalize(display)
            if not term:
                continue
            pos = [clean_gcide(value) for value in re.findall(r"(?s)<pos>(.*?)</pos>", block)]
            definitions = [clean_gcide(value) for value in re.findall(r"(?s)<def>(.*?)</def>", block)]
            examples = [clean_gcide(value) for value in re.findall(r"(?s)<ex>(.*?)</ex>", block)]
            pronunciation = [clean_gcide(value) for value in re.findall(r"(?s)<pr>(.*?)</pr>", block)]
            item = {"w": display, "p": pos, "d": [x for x in definitions if x],
                    "x": [x for x in examples if x], "pr": [x for x in pronunciation if x]}
            if item["d"]:
                records[term].append(item)
    output = DATA / "gcide"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    shard_records: dict[str, dict[str, list[dict]]] = defaultdict(dict)
    for term, values in records.items():
        shard_records[shard_for(term)][term] = values
    for shard, values in shard_records.items():
        write_json(output / f"{shard}.json", values)
    inventory = {
        "schema": PIPELINE_SCHEMA,
        "label": "GNU Collaborative International Dictionary of English",
        "authority": "historical supplemental definitions",
        "version": GCIDE_VERSION,
        "source_url": "https://gcide.gnu.org.ua/download",
        "license": "GPL-3.0-or-later",
        "archive_sha256": file_hash(GCIDE_ARCHIVE),
        "source_entries": source_entries,
        "indexed_terms": len(records),
        "records_with_definitions": sum(len(value) for value in records.values()),
        "shards": len(shard_records),
    }
    write_json(output / "manifest.json", inventory)
    inventory["atlas_terms_after_merge"] = merge_terms(set(records))
    attach_supplement("gcide", inventory)
    write_json(BUILD / "gcide-import.json", inventory)
    print(json.dumps(inventory, indent=2))


def read_stardict_fields(blob: bytes, types: str | None) -> list[tuple[str, bytes]]:
    fields: list[tuple[str, bytes]] = []
    cursor = 0
    if types:
        for index, kind in enumerate(types):
            if kind.isupper():
                if cursor + 4 > len(blob):
                    raise ValueError("Truncated StarDict binary field length")
                size = struct.unpack(">I", blob[cursor:cursor + 4])[0]
                cursor += 4
                value = blob[cursor:cursor + size]
                cursor += size
            else:
                end = blob.find(b"\0", cursor)
                if end < 0:
                    if index != len(types) - 1:
                        raise ValueError("Missing StarDict text field terminator")
                    end = len(blob)
                value, cursor = blob[cursor:end], min(end + 1, len(blob))
            fields.append((kind, value))
        return fields
    while cursor < len(blob):
        kind = chr(blob[cursor])
        cursor += 1
        if kind.isupper():
            size = struct.unpack(">I", blob[cursor:cursor + 4])[0]
            cursor += 4
            fields.append((kind, blob[cursor:cursor + size]))
            cursor += size
        else:
            end = blob.find(b"\0", cursor)
            if end < 0:
                end = len(blob)
            fields.append((kind, blob[cursor:end]))
            cursor = end + 1
    return fields


def parse_ifo(path: Path) -> dict[str, str]:
    rows = path.read_text(encoding="utf-8-sig").splitlines()
    if not rows or "StarDict" not in rows[0]:
        raise ValueError("Not a StarDict .ifo file")
    return dict(line.split("=", 1) for line in rows[1:] if "=" in line)


def import_stardict(args: argparse.Namespace) -> None:
    base = Path(args.path).resolve()
    if base.suffix == ".ifo":
        base = base.with_suffix("")
    ifo_path, idx_path = base.with_suffix(".ifo"), base.with_suffix(".idx")
    metadata = parse_ifo(ifo_path)
    dict_path = base.with_suffix(".dict")
    zipped = Path(str(dict_path) + ".dz")
    dictionary = dict_path.read_bytes() if dict_path.is_file() else gzip.open(zipped, "rb").read()
    offset_size = 8 if metadata.get("idxoffsetbits") == "64" else 4
    zipped_index = Path(str(idx_path) + ".gz")
    index = idx_path.read_bytes() if idx_path.is_file() else gzip.open(zipped_index, "rb").read()
    cursor = 0
    records = []
    while cursor < len(index):
        end = index.index(b"\0", cursor)
        term = index[cursor:end].decode("utf-8")
        cursor = end + 1
        if offset_size == 8:
            offset, size = struct.unpack(">QI", index[cursor:cursor + 12]); cursor += 12
        else:
            offset, size = struct.unpack(">II", index[cursor:cursor + 8]); cursor += 8
        fields = []
        for kind, value in read_stardict_fields(dictionary[offset:offset + size], metadata.get("sametypesequence")):
            fields.append({"type": kind, "text": value.decode("utf-8", errors="replace") if kind.islower() else None,
                           "bytes": len(value)})
        records.append({"term": term, "fields": fields})
    synonym_path = base.with_suffix(".syn")
    synonym_count = 0
    if synonym_path.is_file():
        synonyms = synonym_path.read_bytes()
        cursor = 0
        while cursor < len(synonyms):
            end = synonyms.index(b"\0", cursor)
            alias = synonyms[cursor:end].decode("utf-8")
            cursor = end + 1
            if cursor + 4 > len(synonyms):
                raise ValueError("Truncated StarDict synonym index")
            target_index = struct.unpack(">I", synonyms[cursor:cursor + 4])[0]
            cursor += 4
            if target_index >= len(records):
                raise ValueError(f"StarDict synonym points past the index: {target_index}")
            records[target_index].setdefault("aliases", []).append(alias)
            synonym_count += 1
    output = Path(args.output).resolve() if args.output else BUILD / "stardict" / f"{base.name}.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    manifest = {"schema": PIPELINE_SCHEMA, "format": "StarDict", "bookname": metadata.get("bookname"),
                "source": str(base), "entries": len(records), "synonyms": synonym_count,
                "sametypesequence": metadata.get("sametypesequence"),
                "ifo_sha256": file_hash(ifo_path),
                "idx_sha256": sha256(index).hexdigest(),
                "syn_sha256": file_hash(synonym_path) if synonym_path.is_file() else None,
                "output": str(output)}
    write_json(output.with_suffix(".manifest.json"), manifest)
    print(json.dumps(manifest, indent=2))


def xml_safe(value: str) -> str:
    return "".join(char for char in value if char in "\t\n\r" or ord(char) >= 32)


def export_odict(args: argparse.Namespace) -> None:
    source_dir = DATA / args.source
    if args.shard != "all":
        shards = [args.shard]
    else:
        shards = sorted({path.name[:2] for path in source_dir.glob("[0-9a-f][0-9a-f].json*")})
    output_dir = Path(args.output).resolve() if args.output else BUILD / "odict" / args.source
    output_dir.mkdir(parents=True, exist_ok=True)
    manifests = []
    for shard in sorted(shards):
        path = source_dir / f"{shard}.json"
        compressed_path = source_dir / f"{shard}.json.gz"
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
        elif compressed_path.is_file():
            data = json.loads(gzip.decompress(compressed_path.read_bytes()).decode("utf-8"))
        else:
            raise FileNotFoundError(f"Missing source shard: {path} or {compressed_path}")
        root = ET.Element("dictionary", {"id": f"lexicon-atlas-{args.source}-{shard}",
                                          "name": f"Lexicon Atlas {args.source.title()} {shard}"})
        for term, rows in sorted(data.items()):
            entry = ET.SubElement(root, "entry", {"term": xml_safe(term)})
            for row_index, row in enumerate(rows, start=1):
                ety_attrs = {}
                ety_attrs["id"] = f"{args.source}-{sha256(term.encode('utf-8')).hexdigest()[:12]}-{row_index}"
                if row.get("e"):
                    ety_attrs["description"] = xml_safe(row["e"])
                ety = ET.SubElement(entry, "ety", ety_attrs)
                if args.source == "wiktionary":
                    for pronunciation in row.get("pr") or []:
                        value = pronunciation.get("ipa") or pronunciation.get("enpr")
                        if value:
                            ET.SubElement(ety, "pronunciation", {"kind": "ipa" if pronunciation.get("ipa") else "enpr",
                                                                  "value": xml_safe(value)})
                    source_senses = row.get("s") or [{}]
                    for sense_index, item in enumerate(source_senses):
                        sense = ET.SubElement(ety, "sense", {"pos": row.get("p") or "unknown"})
                        if item.get("id"):
                            ET.SubElement(sense, "tag").text = xml_safe(f"source-id:{item['id']}")
                        for tag in item.get("tags") or []:
                            ET.SubElement(sense, "tag").text = xml_safe(tag)
                        if sense_index == 0:
                            for form in row.get("f") or []:
                                form_node = ET.SubElement(sense, "form", {"term": xml_safe(form["form"]), "kind": "inflection"})
                                for tag in form.get("tags") or []:
                                    ET.SubElement(form_node, "tag").text = xml_safe(tag)
                        glosses = item.get("glosses") or []
                        for gloss in glosses:
                            definition = ET.SubElement(sense, "definition", {"value": xml_safe(gloss)})
                            for example in item.get("examples") or []:
                                ET.SubElement(definition, "example", {"value": xml_safe(example.get("text") or "")})
                else:
                    sense = ET.SubElement(ety, "sense", {"pos": "; ".join(row.get("p") or []) or "unknown"})
                    for definition_text in row.get("d") or []:
                        definition = ET.SubElement(sense, "definition", {"value": xml_safe(definition_text)})
                        for example in (row.get("x") or [])[:10]:
                            ET.SubElement(definition, "example", {"value": xml_safe(example)})
        target = output_dir / f"{shard}.odxml"
        ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)
        ET.parse(target)
        manifests.append({"shard": shard, "entries": len(root), "bytes": target.stat().st_size,
                          "sha256": file_hash(target), "path": str(target)})
    manifest = {"schema": PIPELINE_SCHEMA, "format": "ODict ODXML", "odict_revision": ODICT_REVISION,
                "source": args.source,
                "exported_fields": ["headword", "etymology", "part_of_speech", "pronunciation", "forms", "sense_tags", "definitions", "examples"],
                "omitted_fields": ["Wiktionary synonym, antonym, hypernym, hyponym, and derived-term links"],
                "shards": manifests}
    write_json(output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


def inventory(_: argparse.Namespace) -> None:
    report = {"schema": PIPELINE_SCHEMA, "sources": {}}
    candidates = {
        "wiktionary": WIKTIONARY_FILE,
        "gcide_archive": GCIDE_ARCHIVE,
        "ipa_us": ROOT / "vendor" / "ipa-dict" / "en_US.txt",
        "ipa_uk": ROOT / "vendor" / "ipa-dict" / "en_UK.txt",
    }
    for key, path in candidates.items():
        report["sources"][key] = {"path": str(path), "readable": path.is_file(),
                                    "bytes": path.stat().st_size if path.is_file() else None,
                                    "sha256": file_hash(path) if path.is_file() else None}
    write_json(BUILD / "source-inventory.json", report)
    print(json.dumps(report, indent=2))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name, function in (("import-wiktionary", import_wiktionary),
                           ("import-gcide", import_gcide), ("inventory", inventory)):
        command = commands.add_parser(name)
        command.set_defaults(function=function)
    command = commands.add_parser("import-stardict")
    command.add_argument("path", help="Path to the .ifo file or extensionless StarDict base")
    command.add_argument("--output")
    command.set_defaults(function=import_stardict)
    command = commands.add_parser("export-odict")
    command.add_argument("--source", choices=("wiktionary", "gcide"), required=True)
    command.add_argument("--shard", default="all", help="two-digit shard or all")
    command.add_argument("--output")
    command.set_defaults(function=export_odict)
    return result


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.function(arguments)
