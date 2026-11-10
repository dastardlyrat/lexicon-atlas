# Lexicon Atlas

Lexicon Atlas is a source-aware graphical explorer for words, senses, definitions, pronunciations, grammar, etymology, morphology, and semantic relations. It is designed as a deterministic lexical front end: sources remain visibly separate, spelling collisions stay visible, and lexical evidence never silently becomes a selected meaning or an authorized command.

**Live application:** [lexicon-atlas-oewn.dastardly-rat.chatgpt.site](https://lexicon-atlas-oewn.dastardly-rat.chatgpt.site/)

Lexicon Atlas is part of our developing work on **natural language processing (NLP)**. See the [NLP Development Suite](https://github.com/alia-june/xOSG-prototype/tree/main/nlp-development-suite) in the xOSG Prototype repository for the broader technology. An upcoming project will grow a **dictionary from a seed drawn from classical sources**, keeping each source’s provenance visible as the dictionary develops.

![Illustration of a figure beside a circular geometric motif](assets/phillipe-stuart-artwork.jpg)

*Artwork by phillipe stuart.*

This two-dimensional ink image is a transmigration of a historical artifact. Simulated three-dimensional rendering gives the ink image life and depth, carrying the drawing into a new visual form.

## Repository boundary

This is a **code-only repository**. It contains the interface, data builders, import/export adapters, desktop scaffold, project notes, and artwork. It does not contain dictionaries, WordNet databases, downloaded archives, generated lexical shards, or an automatic data downloader.

The omission is deliberate: each lexical source has its own provenance, version, and redistribution terms. Obtain permitted source data yourself, place it under a machine-local data root, and build `dist/data/` locally. See [DATA_INSTALLATION.md](DATA_INSTALLATION.md).

## Download

Use the [latest code-only release](https://github.com/dastardlyrat/lexicon-atlas/releases/latest) for a versioned ZIP. Release archives contain the application and local builders, but no dictionaries, generated lexical shards, databases, downloaded corpora, or automatic source downloader. Data installation remains a separate user-controlled step.

## What is included

| Area | Purpose |
|---|---|
| `dist/` | Static web interface and source-aware relation graph |
| `dist/modules/synthesis-engine.js` | Pure heuristic synthesis module |
| `build_data.py` | Converts a prepared OEWN database and approved supplements into browser shards |
| `lexical_pipeline.py` | Local import/export adapters for Wiktionary, GCIDE, StarDict, and ODict |
| `odict_bridge.cjs` | Optional ODict compile/query bridge |
| `desktop/` | Loopback-only Electron development shell |
| `MODULE_ARCHITECTURE.md` | Component boundaries and extraction plan |
| `NOTES.md`, `TODO.md` | Current implementation notes and staged work |

## Supported lexical sources

The program can attach the following sources while preserving their records separately:

| Source or format | Use in Lexicon Atlas | Included here? |
|---|---|---:|
| Open English WordNet | Candidate senses and semantic/lexical relations | No |
| CMU Pronouncing Dictionary | General American ARPAbet pronunciations | No |
| Open Dict Data IPA | General American and Received Pronunciation IPA | No |
| UniMorph English | Inflectional forms and derivational links | No |
| English Wiktionary via Kaikki | Supplemental definitions, forms, pronunciations, and etymology | No |
| GCIDE | Historical supplemental definitions | No |
| StarDict | Import format; not treated as an authority | Adapter only |
| ODict | Portable offline export/query format; not treated as an authority | Adapter only |

Source and license links are maintained in [`dist/resources.html`](dist/resources.html). Before redistributing any generated dataset, verify the exact source version and its applicable terms; the code repository does not grant rights to third-party data.

## Architecture

```text
machine-local lexical sources
          |
          v
build_data.py + lexical_pipeline.py
          |
          v
dist/data/  (generated, ignored by Git)
          |
          v
static browser interface
  | senses | full word | synthesis | relation graph |
          |
          +--> optional Electron loopback shell
```

The browser reads deterministic hash-sharded JSON assets. The relation graph follows one selected relation for one to five bounded levels. Its word-chain layout can flow front-to-back or back-to-front. Selecting a graph word raises and highlights its recorded direct connections and displays its part of speech, lexical sense ID, synset ID, and source definition. The default `entity` hyponym view exercises the full five-level bounded presentation. The synthesis view ranks attached records with explicit source weights and lexical overlap; it remains a proposal rather than authority.

## Start locally

After installing data as described in [DATA_INSTALLATION.md](DATA_INSTALLATION.md):

```powershell
python -m http.server 8000 --directory dist
```

Then open `http://127.0.0.1:8000/`.

For the desktop development shell:

```powershell
cd desktop
npm install
npm start
```

The shell is a scaffold, not a packaged installer.

## Truth and authority boundary

- A shared spelling does not establish a shared meaning.
- A dictionary record is source evidence, not accepted canon.
- A ranked interpretation is generated synthesis, not a selected sense.
- Lexical analysis does not create an axiom, grant command authority, or execute a command.
- Optional AI support is inert unless a caller explicitly supplies `window.lexiconAtlasAI`; its output remains generated draft text.

## License

The original code, documentation, and published project assets in this repository are licensed under the [MIT License](LICENSE), copyright 2026 `dastardlyrat`.

The MIT License does **not** relicense external dictionaries, lexical databases, generated records derived from them, or third-party dependencies. Those materials are excluded from this repository and retain their own licenses and attribution requirements. See [`dist/resources.html`](dist/resources.html) for the source-by-source ledger.
