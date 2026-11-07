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
python lexical_pipeline.py import-wiktionary
python lexical_pipeline.py import-gcide
python validate_build.py
```

`build_data.py` replaces `dist/data/`; therefore run supplemental imports after the base build. All generated output remains ignored by Git.

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
