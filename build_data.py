"""Export the verified OEWN SQLite database into static browser shards."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3


ROOT = Path(__file__).resolve().parent
SHARED_ROOT = Path(os.environ["LEXICON_DATA_ROOT"]).expanduser() if os.environ.get("LEXICON_DATA_ROOT") else None
DATABASE = (SHARED_ROOT / "oewn" / "wn.db") if SHARED_ROOT else ROOT.parent / ".wn_data" / "wn.db"
DATA = ROOT / "dist" / "data"
SOURCE_ROOT = SHARED_ROOT or ROOT / "vendor"
CMUDICT = SOURCE_ROOT / "cmudict" / "cmudict.dict"
CMUDICT_LICENSE = SOURCE_ROOT / "cmudict" / "LICENSE"
UNIMORPH = SOURCE_ROOT / "unimorph-eng" / "eng"
UNIMORPH_DERIVATIONS = SOURCE_ROOT / "unimorph-eng" / "eng.derivations.tsv"
UNIMORPH_README = SOURCE_ROOT / "unimorph-eng" / "README.md"
IPA_US = SOURCE_ROOT / "ipa-dict" / "en_US.txt"
IPA_UK = SOURCE_ROOT / "ipa-dict" / "en_UK.txt"
IPA_LICENSE = SOURCE_ROOT / "ipa-dict" / "LICENSE"
CMUDICT_REVISION = "74790861f652b15e4ac49015a90074ad62a27690"
UNIMORPH_REVISION = "66e0e9e8e2dcd196da081a25a48e5c1fe3d8b49b"
IPA_REVISION = "43c3570eb3553bdd19fccd2bd0091534889af023"
EXPECTED = {"words": 135_969, "synsets": 107_519, "senses": 185_129}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def primary_forms(connection: sqlite3.Connection) -> dict[int, str]:
    result: dict[int, str] = {}
    for entry_rowid, form in connection.execute(
            "SELECT entry_rowid, form FROM forms ORDER BY entry_rowid, rank, rowid"):
        result.setdefault(entry_rowid, form)
    return result


def normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def load_supplements() -> tuple[dict[str, dict], dict[str, int]]:
    required = [CMUDICT, CMUDICT_LICENSE, UNIMORPH, UNIMORPH_DERIVATIONS,
                UNIMORPH_README, IPA_US, IPA_UK, IPA_LICENSE]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing attached lexical sources: " + ", ".join(missing))

    records: dict[str, dict] = defaultdict(dict)
    pronunciation_count = 0
    with CMUDICT.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip() or line.startswith(";;;"):
                continue
            try:
                headword, phones = line.rstrip().split(maxsplit=1)
            except ValueError:
                continue
            term = normalized(re.sub(r"\(\d+\)$", "", headword))
            if not term:
                continue
            pronunciations = records[term].setdefault("p", [])
            if phones not in pronunciations:
                pronunciations.append(phones)
                pronunciation_count += 1

    form_count = 0
    paradigm_lemmas: set[str] = set()
    with UNIMORPH.open(encoding="utf-8") as source:
        for line in source:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 3:
                continue
            lemma, form, features = map(str.strip, parts)
            lemma_key, form_key = normalized(lemma), normalized(form)
            if not lemma_key or not form_key:
                continue
            paradigm_lemmas.add(lemma_key)
            row = [form, features]
            forms = records[lemma_key].setdefault("f", [])
            if row not in forms:
                forms.append(row)
                form_count += 1
            lemmas = records[form_key].setdefault("l", [])
            if lemma not in lemmas:
                lemmas.append(lemma)

    derivation_count = 0
    with UNIMORPH_DERIVATIONS.open(encoding="utf-8") as source:
        for line in source:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 4:
                continue
            source_word, target_word, pos_change, affix = map(str.strip, parts)
            source_key, target_key = normalized(source_word), normalized(target_word)
            if not source_key or not target_key:
                continue
            records[source_key].setdefault("d", []).append(["out", target_word, pos_change, affix])
            records[target_key].setdefault("d", []).append(["in", source_word, pos_change, affix])
            derivation_count += 1

    ipa_count = 0
    for ipa_path, dialect, upstream_license in (
            (IPA_US, "General American", "MIT-derived"),
            (IPA_UK, "Received Pronunciation", "GPL-3.0-derived")):
        with ipa_path.open(encoding="utf-8") as source:
            for line in source:
                parts = line.rstrip("\n").split("\t", 1)
                if len(parts) != 2:
                    continue
                headword, value = map(str.strip, parts)
                term = normalized(headword)
                if not term or not value:
                    continue
                for pronunciation in (item.strip() for item in value.split(",")):
                    if not pronunciation:
                        continue
                    row = [dialect, pronunciation, upstream_license]
                    ipas = records[term].setdefault("i", [])
                    if row not in ipas:
                        ipas.append(row)
                        ipa_count += 1

    return dict(records), {
        "pronunciations": pronunciation_count,
        "paradigm_lemmas": len(paradigm_lemmas),
        "forms": form_count,
        "derivations": derivation_count,
        "ipa_pronunciations": ipa_count,
    }


def main() -> None:
    if not DATABASE.is_file():
        raise FileNotFoundError(f"Missing WordNet database: {DATABASE}")
    resolved = DATA.resolve()
    if resolved.name != "data" or resolved.parent.name != "dist":
        raise RuntimeError("Refusing to replace an unexpected data directory")
    if DATA.exists():
        shutil.rmtree(DATA)
    (DATA / "words").mkdir(parents=True)
    (DATA / "synsets").mkdir(parents=True)
    (DATA / "lexical").mkdir(parents=True)

    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    lexicon = connection.execute(
        "SELECT rowid, id, version, label, language, license, url FROM lexicons "
        "WHERE id = 'oewn' AND version = '2025'").fetchone()
    if lexicon is None:
        raise RuntimeError("The pinned oewn:2025 lexicon is not installed")
    lexicon_id = lexicon["rowid"]
    counts = {
        "words": connection.execute("SELECT COUNT(*) FROM entries WHERE lexicon_rowid=?", (lexicon_id,)).fetchone()[0],
        "synsets": connection.execute("SELECT COUNT(*) FROM synsets WHERE lexicon_rowid=?", (lexicon_id,)).fetchone()[0],
        "senses": connection.execute("SELECT COUNT(*) FROM senses WHERE lexicon_rowid=?", (lexicon_id,)).fetchone()[0],
    }
    if counts != EXPECTED:
        raise RuntimeError(f"WordNet counts differ from verified release: {counts}")

    relation_types = dict(connection.execute("SELECT rowid, type FROM relation_types"))
    entry_lemmas = primary_forms(connection)

    sense_rows: dict[int, dict] = {}
    sense_entry_rowids: dict[int, int] = {}
    senses_by_entry: dict[int, list[dict]] = defaultdict(list)
    for row in connection.execute(
            "SELECT s.rowid, s.id, s.entry_rowid, sy.id AS synset_id "
            "FROM senses s JOIN synsets sy ON sy.rowid=s.synset_rowid "
            "WHERE s.lexicon_rowid=? ORDER BY s.entry_rowid, s.entry_rank, s.rowid", (lexicon_id,)):
        record = {"id": row["id"], "synset": row["synset_id"], "relations": {}}
        sense_rows[row["rowid"]] = record
        sense_entry_rowids[row["rowid"]] = row["entry_rowid"]
        senses_by_entry[row["entry_rowid"]].append(record)

    lexical_groups: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in connection.execute(
            "SELECT r.source_rowid, r.target_rowid, r.type_rowid, ts.id AS target_id, "
            "ts.entry_rowid AS target_entry, tsy.id AS target_synset "
            "FROM sense_relations r JOIN senses ts ON ts.rowid=r.target_rowid "
            "JOIN synsets tsy ON tsy.rowid=ts.synset_rowid WHERE r.lexicon_rowid=? "
            "ORDER BY r.source_rowid, r.type_rowid, ts.id", (lexicon_id,)):
        lexical_groups[row["source_rowid"]][relation_types[row["type_rowid"]]].append({
            "sense": row["target_id"], "lemma": entry_lemmas[row["target_entry"]],
            "synset": row["target_synset"],
        })
    for sense_rowid, groups in lexical_groups.items():
        sense_rows[sense_rowid]["relations"] = dict(groups)
    senses_by_synset: dict[str, list[dict]] = defaultdict(list)
    for sense_rowid, record in sense_rows.items():
        senses_by_synset[record["synset"]].append({
            "id": record["id"],
            "lemma": entry_lemmas[sense_entry_rowids[sense_rowid]],
            "relations": record["relations"],
        })
    for records in senses_by_synset.values():
        records.sort(key=lambda item: item["id"])

    word_shards: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    terms: set[str] = set()
    seen_word_records: set[tuple[str, str]] = set()
    for row in connection.execute(
            "SELECT f.form, e.id, e.rowid AS entry_rowid, e.pos FROM forms f "
            "JOIN entries e ON e.rowid=f.entry_rowid WHERE e.lexicon_rowid=? "
            "ORDER BY lower(f.form), e.id, f.rank, f.rowid", (lexicon_id,)):
        term = normalized(row["form"])
        key = (term, row["id"])
        if not term or key in seen_word_records:
            continue
        seen_word_records.add(key)
        terms.add(term)
        shard = sha256(term.encode("utf-8")).hexdigest()[:2]
        word_shards[shard][term].append({
            "id": row["id"], "lemma": entry_lemmas[row["entry_rowid"]],
            "pos": row["pos"], "senses": senses_by_entry[row["entry_rowid"]],
        })
    supplements, supplement_counts = load_supplements()
    terms.update(supplements)
    lexical_shards: dict[str, dict[str, dict]] = defaultdict(dict)
    for term, record in supplements.items():
        shard = sha256(term.encode("utf-8")).hexdigest()[:2]
        lexical_shards[shard][term] = record
    for shard, records in lexical_shards.items():
        write_json(DATA / "lexical" / f"{shard}.json", records)

    for shard, records in word_shards.items():
        write_json(DATA / "words" / f"{shard}.json", records)
    write_json(DATA / "terms.json", sorted(terms))

    synsets: dict[int, dict] = {}
    for row in connection.execute(
            "SELECT rowid, id, pos FROM synsets WHERE lexicon_rowid=? ORDER BY id", (lexicon_id,)):
        synsets[row["rowid"]] = {"id": row["id"], "pos": row["pos"],
                                 "lemmas": [], "definition": None, "examples": [], "relations": {},
                                 "senses": senses_by_synset.get(row["id"], [])}
    for synset_rowid, definition in connection.execute(
            "SELECT synset_rowid, definition FROM definitions WHERE lexicon_rowid=? "
            "ORDER BY synset_rowid, rowid", (lexicon_id,)):
        if synsets[synset_rowid]["definition"] is None:
            synsets[synset_rowid]["definition"] = definition
    for synset_rowid, example in connection.execute(
            "SELECT synset_rowid, example FROM synset_examples WHERE lexicon_rowid=? "
            "ORDER BY synset_rowid, rowid", (lexicon_id,)):
        synsets[synset_rowid]["examples"].append(example)
    for synset_rowid, entry_rowid in connection.execute(
            "SELECT synset_rowid, entry_rowid FROM senses WHERE lexicon_rowid=? "
            "ORDER BY synset_rowid, synset_rank, rowid", (lexicon_id,)):
        lemma = entry_lemmas[entry_rowid]
        if lemma not in synsets[synset_rowid]["lemmas"]:
            synsets[synset_rowid]["lemmas"].append(lemma)
    semantic_groups: dict[int, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in connection.execute(
            "SELECT r.source_rowid, r.type_rowid, target.id AS target_id "
            "FROM synset_relations r JOIN synsets target ON target.rowid=r.target_rowid "
            "WHERE r.lexicon_rowid=? ORDER BY r.source_rowid, r.type_rowid, target.id", (lexicon_id,)):
        semantic_groups[row["source_rowid"]][relation_types[row["type_rowid"]]].append(row["target_id"])
    synset_shards: dict[str, dict[str, dict]] = defaultdict(dict)
    for rowid, record in synsets.items():
        record["relations"] = dict(semantic_groups.get(rowid, {}))
        match = re.match(r"oewn-(\d{2})", record["id"])
        shard = match.group(1) if match else "other"
        synset_shards[shard][record["id"]] = record
    for shard, records in synset_shards.items():
        write_json(DATA / "synsets" / f"{shard}.json", records)

    manifest = {
        "schema": "lexicon-atlas-data/4", "release": "oewn:2025",
        "label": lexicon["label"], "language": lexicon["language"],
        "license": lexicon["license"], "source_url": lexicon["url"],
        "counts": counts, "terms": len(terms),
        "word_shards": len(word_shards), "synset_shards": len(synset_shards),
        "source_database_sha256": sha256(DATABASE.read_bytes()).hexdigest(),
        "supplements": {
            "cmudict": {
                "label": "CMU Pronouncing Dictionary", "scope": "US English pronunciations",
                "license": "Unrestricted use; attribution requested", "source_url": "https://github.com/cmusphinx/cmudict",
                "revision": CMUDICT_REVISION,
                "source_sha256": sha256(CMUDICT.read_bytes()).hexdigest(),
                "records": supplement_counts["pronunciations"],
            },
            "unimorph": {
                "label": "UniMorph English", "scope": "inflectional forms and derivational links",
                "license": "CC BY-SA 3.0", "source_url": "https://github.com/unimorph/eng",
                "revision": UNIMORPH_REVISION,
                "source_sha256": sha256(UNIMORPH.read_bytes()).hexdigest(),
                "derivations_sha256": sha256(UNIMORPH_DERIVATIONS.read_bytes()).hexdigest(),
                "paradigm_lemmas": supplement_counts["paradigm_lemmas"],
                "forms": supplement_counts["forms"], "derivations": supplement_counts["derivations"],
            },
            "ipa_dict": {
                "label": "Open Dict Data IPA", "scope": "General American and Received Pronunciation IPA",
                "license": "Project MIT; en_US MIT-derived; en_UK GPL-3.0-derived",
                "source_url": "https://github.com/open-dict-data/ipa-dict",
                "revision": IPA_REVISION,
                "en_us_sha256": sha256(IPA_US.read_bytes()).hexdigest(),
                "en_uk_sha256": sha256(IPA_UK.read_bytes()).hexdigest(),
                "records": supplement_counts["ipa_pronunciations"],
            },
            "wiktionary": {
                "label": "English Wiktionary", "scope": "live fallback definitions and full entry link",
                "license": "CC BY-SA and GFDL", "source_url": "https://en.wiktionary.org/",
                "mode": "live",
            },
        },
        "lexical_shards": len(lexical_shards),
    }
    write_json(DATA / "manifest.json", manifest)
    connection.close()
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
