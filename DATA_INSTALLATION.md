# Data installation

Lexicon Atlas intentionally ships without dictionaries and without an automatic downloader. This document describes the expected drop-in layout; it does not authorize redistribution of any source.

## Central data root

Set `LEXICON_DATA_ROOT` to a machine-local directory shared by lexical projects:

```powershell
$env:LEXICON_DATA_ROOT = 'D:\Lexicon Data'
```

Expected layout:

```text
Lexicon Data/
├── oewn/
│   └── wn.db
├── cmudict/
│   ├── cmudict.dict
│   └── LICENSE
├── unimorph-eng/
│   ├── eng
│   ├── eng.derivations.tsv
│   └── README.md
├── ipa-dict/
│   ├── en_US.txt
│   ├── en_UK.txt
│   └── LICENSE
├── wiktionary/
│   └── kaikki.org-dictionary-English.jsonl
└── gcide/
    ├── gcide-0.54/
    └── gcide-0.54.tar.xz   (optional when the extracted directory exists)
```

The builders verify required paths and record source hashes in generated manifests. They do not prove that you have redistribution permission.

## Build browser data

From the repository root:

```powershell
python build_data.py
python lexical_pipeline.py import-wiktionary  # optional local supplement
python lexical_pipeline.py import-gcide       # optional local supplement
python finalize_data.py
python validate_build.py
```

`build_data.py` replaces `dist/data/`; therefore run supplemental imports after the base build. `finalize_data.py` is the required final step before validation or browser use. It parses the staged JSON, writes deterministic gzip assets with zeroed gzip time metadata, atomically replaces only the corresponding browser files, and records relative paths, sizes, and SHA-256 values in `dist/data/artifact-inventory.json`.

The finalizer does not download data, merge source records, remove staging JSON, or operate outside this checkout's exact `dist/data/` directory. Production hash-sharded families must contain all 256 shards. A failed preflight leaves existing finalized files untouched, and a replacement failure attempts a complete rollback.

Wiktionary and GCIDE imports are optional. Omit an import when its permitted source is not installed; the generated manifest must accurately retain that source as absent or live fallback. All staged and finalized output remains ignored by Git.

The ordinary regression suite uses invented synthetic records and no external corpus:

```powershell
python -B -m unittest discover -s tests -v
```

The synthetic validation profile is test-only. Normal local builds continue to use the validator's default production profile.

## StarDict and ODict

Import an already obtained StarDict dictionary without merging its authority into another source:

```powershell
python lexical_pipeline.py import-stardict D:\Dictionaries\example.ifo
```

Export a locally built source to ODict XML:

```powershell
python lexical_pipeline.py export-odict --source wiktionary --shard 4a
python lexical_pipeline.py export-odict --source gcide --shard all
```

Generated adapter output is written under `build-output/`, which is also ignored.

## Pre-publication guard

Before committing, run:

```powershell
python verify_code_only.py
```

The guard rejects external-data directories, generated lexical shards, database files, dictionary binaries, archives, and files over the repository size ceiling.
